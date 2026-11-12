"""Bounded WinMM playback for interleaved signed 16-bit stereo PCM."""

import ctypes as c
import sys
from threading import Lock, Thread


PCM_FRAME_BYTES = 4
BUFFER_COUNT = 4
BUFFER_MS = 20
PENDING_MS = 80
WAVE_MAPPER = 0xFFFFFFFF
CALLBACK_EVENT = 0x00050000
WHDR_DONE = 0x00000001
INFINITE = 0xFFFFFFFF
_FAILED_DEVICE_RESOURCES = []

DWORD = c.c_uint32
WORD = c.c_uint16
HANDLE = c.c_void_p
DWORD_PTR = c.c_size_t


class WaveFormat(c.Structure):
    _pack_ = 1
    _fields_ = [
        ("format", WORD), ("channels", WORD), ("rate", DWORD),
        ("byte_rate", DWORD), ("alignment", WORD), ("bits", WORD), ("extra", WORD),
    ]


class WaveHeader(c.Structure):
    _fields_ = [
        ("data", HANDLE), ("length", DWORD), ("recorded", DWORD), ("user", DWORD_PTR),
        ("flags", DWORD), ("loops", DWORD), ("next", HANDLE), ("reserved", DWORD_PTR),
    ]


def _bind(dll, name, result, *arguments):
    fn = getattr(dll, name)
    fn.argtypes = arguments
    fn.restype = result
    return fn


class WaveOut:
    """Own one default endpoint on an event-driven worker, outside the guest clock."""

    def __init__(self, rate):
        if not 8000 <= rate <= 192000:
            raise ValueError(f"Unsupported DOS audio sample rate: {rate}")
        if _FAILED_DEVICE_RESOURCES:
            raise OSError("A previous audio device could not be closed. Restart SimAnt to retry.")
        winmm = c.WinDLL("winmm")
        kernel = c.WinDLL("kernel32", use_last_error=True)
        self._open = _bind(winmm, "waveOutOpen", DWORD, c.POINTER(HANDLE), DWORD,
                           c.POINTER(WaveFormat), DWORD_PTR, DWORD_PTR, DWORD)
        self._prepare = _bind(winmm, "waveOutPrepareHeader", DWORD, HANDLE, c.POINTER(WaveHeader), DWORD)
        self._write = _bind(winmm, "waveOutWrite", DWORD, HANDLE, c.POINTER(WaveHeader), DWORD)
        self._reset = _bind(winmm, "waveOutReset", DWORD, HANDLE)
        self._unprepare = _bind(winmm, "waveOutUnprepareHeader", DWORD, HANDLE, c.POINTER(WaveHeader), DWORD)
        self._close = _bind(winmm, "waveOutClose", DWORD, HANDLE)
        self._signal = _bind(kernel, "SetEvent", c.c_int, HANDLE)
        self._close_handle = _bind(kernel, "CloseHandle", c.c_int, HANDLE)
        self._wait = _bind(kernel, "WaitForMultipleObjects", DWORD, DWORD, c.POINTER(HANDLE), c.c_int, DWORD)
        create = _bind(kernel, "CreateEventW", HANDLE, HANDLE, c.c_int, c.c_int, c.c_wchar_p)

        self._lock = Lock()
        self._pending = bytearray()
        self._block_frames = rate * BUFFER_MS // 1000
        self._block_bytes = self._block_frames * PCM_FRAME_BYTES
        self._pending_limit = (rate * PENDING_MS // 1000) * PCM_FRAME_BYTES
        self._format = WaveFormat(1, 2, rate, rate * PCM_FRAME_BYTES, PCM_FRAME_BYTES, 16, 0)
        self._stopping = False
        self.error = None
        self.submitted_frames = 0
        self.played_frames = 0
        self.dropped_frames = 0
        self._events = []
        self._worker = Thread(target=self._play, name="SimAnt DOS Audio", daemon=True)
        try:
            for _ in range(3):
                event = create(None, False, False, None)
                if not event:
                    raise c.WinError(c.get_last_error())
                self._events.append(event)
            self._worker.start()
        except (OSError, RuntimeError):
            self._dispose_events()
            raise

    def submit(self, pointer, frames):
        """Copy only available queue space while the borrowed Libretro PCM is valid."""
        if not frames or not pointer:
            return
        if not self._lock.acquire(blocking=False):
            self.dropped_frames += frames
            return
        try:
            if self._stopping or not self._events:
                return
            available = (self._pending_limit - len(self._pending)) // PCM_FRAME_BYTES
            accepted = min(available, frames)
            self.dropped_frames += frames - accepted
            if accepted:
                self._pending.extend(c.string_at(pointer, accepted * PCM_FRAME_BYTES))
                self._signal(self._events[1])
        finally:
            self._lock.release()

    def close(self):
        with self._lock:
            self._stopping = True
            if self._events:
                self._signal(self._events[0])
        self._worker.join(timeout=2)
        if self._worker.is_alive():
            self._diagnose("the playback worker did not stop within two seconds")

    def _diagnose(self, error):
        if self.error is None:
            self.error = str(error)
            print(f"DOS audio unavailable: {self.error}", file=sys.stderr)

    def _dispose_events(self, keep_completion=False):
        with self._lock:
            events, self._events = self._events, []
            self._pending.clear()
        for event in events[:2] if keep_completion else events:
            self._close_handle(event)

    @staticmethod
    def _check(result, operation):
        if result:
            raise OSError(f"{operation} failed (WinMM error {result})")

    def _play(self):
        device = HANDLE()
        slots = []
        inflight = set()
        header_size = c.sizeof(WaveHeader)
        events = (HANDLE * 3)(*self._events)
        try:
            self._check(self._open(c.byref(device), WAVE_MAPPER, c.byref(self._format),
                                   events[2], 0, CALLBACK_EVENT), "waveOutOpen")
            for _ in range(BUFFER_COUNT):
                buffer = c.create_string_buffer(self._block_bytes)
                header = WaveHeader(c.addressof(buffer), self._block_bytes)
                self._check(self._prepare(device, c.byref(header), header_size), "waveOutPrepareHeader")
                slots.append((buffer, header))

            while True:
                signaled = self._wait(len(events), events, False, INFINITE)
                if signaled == 0:
                    break
                if signaled not in (1, 2):
                    raise c.WinError(c.get_last_error())
                for index, (buffer, header) in enumerate(slots):
                    if index in inflight:
                        if not header.flags & WHDR_DONE:
                            continue
                        self.played_frames += self._block_frames
                        inflight.remove(index)
                    with self._lock:
                        if self._stopping or len(self._pending) < self._block_bytes:
                            continue
                        block = bytes(self._pending[:self._block_bytes])
                        del self._pending[:self._block_bytes]
                    c.memmove(buffer, block, self._block_bytes)
                    self._check(self._write(device, c.byref(header), header_size), "waveOutWrite")
                    self.submitted_frames += self._block_frames
                    inflight.add(index)
        except OSError as error:
            self._diagnose(error)
        finally:
            keep_completion = bool(device and not self._cleanup_device(device, slots, header_size))
            self._dispose_events(keep_completion)

    def _cleanup_device(self, device, slots, header_size):
        result = self._reset(device)
        if result:
            self._diagnose(f"waveOutReset failed (WinMM error {result})")
        for _, header in slots:
            result = self._unprepare(device, c.byref(header), header_size)
            if result:
                self._diagnose(f"waveOutUnprepareHeader failed (WinMM error {result})")
        result = self._close(device)
        if result:
            self._diagnose(f"waveOutClose failed (WinMM error {result})")
            # A driver refusing to close can still reference its buffers and event.
            _FAILED_DEVICE_RESOURCES.append((device, slots, self._events[2]))
        return result == 0
