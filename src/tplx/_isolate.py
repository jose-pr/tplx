"""Sandboxed renders in a worker process: what `SandboxLimits.timeout` and `max_memory` need.

The parent writes length-prefixed pickles to the worker's standard input and
reads its replies from the worker's standard output. A reply that does not
come within `timeout`, or a worker that ends, fails the call with
`SandboxError`, and the next call starts a new worker. The memory limit is
the operating system's: an address-space limit on Linux, a job object on
Windows, a watch on peak resident memory on macOS (which enforces neither).
"""

from __future__ import annotations

import atexit
import dataclasses
import os
import pickle
import queue
import struct
import subprocess
import sys
import threading
from collections import OrderedDict
from typing import IO, Any, Dict, Optional, Tuple

from .exceptions import RenderError, SandboxError

#: How many workers stay alive at once, one per distinct loader configuration.
MAX_WORKERS = 4

#: The worker's exit status when its memory watch stops it.
_OVER_MEMORY = 3

#: Seconds a new worker may take to start, whatever the render's `timeout`.
_START_TIMEOUT = 60.0

_HEADER = struct.Struct("!Q")


def _send(stream: IO[bytes], payload: bytes) -> None:
    stream.write(_HEADER.pack(len(payload)))
    stream.write(payload)
    stream.flush()


def _receive(stream: IO[bytes]) -> Optional[bytes]:
    """The next message, or None at the end of the stream."""
    header = stream.read(_HEADER.size)
    if len(header) < _HEADER.size:
        return None
    (size,) = _HEADER.unpack(header)
    payload = stream.read(size)
    return payload if len(payload) == size else None


# -- the parent side ----------------------------------------------------------------------


def call(loader: Any, request: Tuple[Any, ...], what: str) -> Any:
    """Run `request` in the worker for `loader`'s configuration and return its result."""
    spec = _spec(loader)
    # A worker's memory limit is set when it starts, so the limits are its key too.
    key = (spec, loader.limits.timeout, loader.limits.max_memory)
    with _LOCK:
        worker = _WORKERS.get(key)
        if worker is None or not worker.alive:
            worker = _WORKERS[key] = _Worker(spec, loader.limits)
            while len(_WORKERS) > MAX_WORKERS:
                _WORKERS.popitem(last=False)[1].close()
        _WORKERS.move_to_end(key)
    return worker.call(request, what)


def _spec(loader: Any) -> bytes:
    """Everything a worker needs to build `loader` again, pickled."""
    limits = dataclasses.replace(loader.limits, timeout=None, max_memory=None)
    spec = {
        "roots": loader.roots,
        "engines": loader.engines,
        "undefined": loader.undefined,
        "globals": loader.globals,
        "encoder": loader.encoder,
        "configure": loader.configure,
        "sandbox": limits,
    }
    return _pickled(spec, "the loader's roots, engines, globals, encoder or configure")


def _pickled(value: Any, what: str) -> bytes:
    try:
        return pickle.dumps(value, protocol=pickle.HIGHEST_PROTOCOL)
    except Exception as exc:
        raise SandboxError(
            f"{what} cannot cross to the sandbox's worker process: {exc}"
        ) from exc


def _interpreter() -> str:
    """The Python to start: on Windows a virtual environment's `python.exe` is a
    launcher that starts the real one as its child, outside the worker's job."""
    if sys.platform == "win32":
        return getattr(sys, "_base_executable", None) or sys.executable
    return sys.executable


class _Worker:
    """One worker process and the thread reading its replies."""

    def __init__(self, spec: bytes, limits: Any) -> None:
        self.timeout: Optional[float] = limits.timeout
        self.max_memory: Optional[int] = limits.max_memory
        environment = dict(os.environ)
        # The worker imports tplx, the engines and whatever the data pickles
        # by reference from the same places as this process.
        environment["PYTHONPATH"] = os.pathsep.join(
            entry for entry in sys.path if isinstance(entry, str)
        )
        self._process = subprocess.Popen(
            [_interpreter(), "-c", "from tplx._isolate import main; main()"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            env=environment,
        )
        self._job = None
        if self.max_memory is not None and sys.platform == "win32":
            self._job = _windows_job(self._process.pid, self.max_memory)
        self._lock = threading.Lock()
        self._replies: "queue.Queue[Optional[bytes]]" = queue.Queue()
        reader = threading.Thread(target=self._read, daemon=True)
        reader.start()
        self.alive = True
        start = ("start", list(sys.path), self.max_memory)
        self.call(start, "starting the worker", _START_TIMEOUT)
        self.call(("loader", spec), "building the loader in the worker", _START_TIMEOUT)

    def _read(self) -> None:
        stdout = self._process.stdout
        assert stdout is not None
        while True:
            payload = _receive(stdout)
            self._replies.put(payload)
            if payload is None:
                return

    def call(
        self, request: Tuple[Any, ...], what: str, timeout: Optional[float] = None
    ) -> Any:
        payload = _pickled(request, f"{what}: the data")
        timeout = self.timeout if timeout is None else timeout
        with self._lock:
            if not self.alive:
                raise SandboxError(f"{what}: the sandbox's worker has ended")
            try:
                stdin = self._process.stdin
                assert stdin is not None
                _send(stdin, payload)
                reply = self._replies.get(timeout=timeout)
            except queue.Empty:
                self.close()
                raise SandboxError(
                    f"{what}: ran past the sandbox's timeout ({timeout} s)"
                ) from None
            except OSError:
                reply = None
            if reply is None:
                self.close()
                status = self._process.poll()
                cause = (
                    "the render passed max_memory"
                    if status == _OVER_MEMORY
                    else f"it ended with status {status}"
                )
                raise SandboxError(f"{what}: the sandbox's worker stopped: {cause}")
        try:
            outcome, value = pickle.loads(reply)
        except Exception as exc:
            raise SandboxError(f"{what}: the worker's reply cannot be read: {exc}")
        if outcome == "error":
            raise value
        return value

    def close(self) -> None:
        """Stop the worker; a call in progress fails."""
        self.alive = False
        process = self._process
        if process.poll() is None:
            process.kill()
        process.wait()
        for stream in (process.stdin, process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        if self._job is not None:
            import ctypes

            ctypes.WinDLL("kernel32").CloseHandle(self._job)
            self._job = None


_LOCK = threading.Lock()
_WORKERS: "OrderedDict[Tuple[bytes, Optional[float], Optional[int]], _Worker]" = (
    OrderedDict()
)


@atexit.register
def _close_all() -> None:
    with _LOCK:
        while _WORKERS:
            _WORKERS.popitem()[1].close()


def _windows_job(pid: int, limit: int) -> Any:
    """A job object holding process `pid` to `limit` bytes of committed memory,
    and ending it when this process ends."""
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64),
            ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD),
            ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t),
            ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t),
            ("PriorityClass", wintypes.DWORD),
            ("SchedulingClass", wintypes.DWORD),
        ]

    class _Counters(ctypes.Structure):
        _fields_ = [
            (name, ctypes.c_uint64)
            for name in (
                "ReadOperationCount",
                "WriteOperationCount",
                "OtherOperationCount",
                "ReadTransferCount",
                "WriteTransferCount",
                "OtherTransferCount",
            )
        ]

    class _Extended(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", _Basic),
            ("IoInfo", _Counters),
            ("ProcessMemoryLimit", ctypes.c_size_t),
            ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t),
            ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE,
        ctypes.c_int,
        ctypes.c_void_p,
        wintypes.DWORD,
    )
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        raise ctypes.WinError(ctypes.get_last_error())
    info = _Extended()
    # JOB_OBJECT_LIMIT_PROCESS_MEMORY | JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    info.BasicLimitInformation.LimitFlags = 0x0100 | 0x2000
    info.ProcessMemoryLimit = limit
    # 9 is JobObjectExtendedLimitInformation.
    if not kernel32.SetInformationJobObject(
        job, 9, ctypes.byref(info), ctypes.sizeof(info)
    ):
        error = ctypes.get_last_error()
        kernel32.CloseHandle(job)
        raise ctypes.WinError(error)
    # PROCESS_SET_QUOTA | PROCESS_TERMINATE
    process = kernel32.OpenProcess(0x0100 | 0x0001, False, pid)
    try:
        if not process or not kernel32.AssignProcessToJobObject(job, process):
            error = ctypes.get_last_error()
            kernel32.CloseHandle(job)
            raise ctypes.WinError(error)
    finally:
        if process:
            kernel32.CloseHandle(process)
    return job


# -- the worker side ----------------------------------------------------------------------


def main() -> None:
    """The worker: answer requests on standard input until it closes."""
    requests = sys.stdin.buffer
    replies = sys.stdout.buffer
    # Anything printed goes to standard error, never into the replies.
    sys.stdout = sys.stderr
    state: Dict[str, Any] = {}
    while True:
        payload = _receive(requests)
        if payload is None:
            return
        try:
            reply: Tuple[str, Any] = ("ok", _handle(pickle.loads(payload), state))
        except Exception as exc:
            if _out_of_memory(exc):
                limit = state.get("max_memory")
                exc = SandboxError(f"the render passed max_memory ({limit} bytes)")
            reply = ("error", exc)
        try:
            message = pickle.dumps(reply, protocol=pickle.HIGHEST_PROTOCOL)
        except Exception as exc:
            message = pickle.dumps(
                ("error", RenderError(f"the result cannot be sent back: {exc}"))
            )
        _send(replies, message)


def _out_of_memory(error: Optional[BaseException]) -> bool:
    """Is `error`, or what it was raised from, a `MemoryError`?"""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, MemoryError):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


def _handle(request: Tuple[Any, ...], state: Dict[str, Any]) -> Any:
    kind = request[0]
    if kind == "start":
        _, path, max_memory = request
        sys.path[:] = path
        state["max_memory"] = max_memory
        if max_memory is not None:
            _limit_memory(max_memory)
        return None
    if kind == "loader":
        from ._loader import Loader

        spec = pickle.loads(request[1])
        roots = spec.pop("roots")
        state["loader"] = Loader(roots, **spec)
        return None
    loader = state["loader"]
    if kind == "render":
        _, candidates, paths, name, data, overrides = request
        lookup = loader.lookup(candidates=candidates, paths=paths)
        return lookup.render(name, data, **overrides)
    if kind == "eval":
        _, candidates, paths, text, context, engine, overrides = request
        lookup = loader.lookup(candidates=candidates, paths=paths)
        return lookup.eval(text, context, engine=engine, **overrides)
    raise ValueError(f"unknown request {kind!r}")


def _limit_memory(limit: int) -> None:
    """Hold this process to `limit` bytes where the system enforces it, else watch it."""
    if sys.platform == "win32":
        return  # the parent put this process in a job object
    import resource

    if sys.platform != "darwin":
        try:
            resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
            return
        except (ValueError, OSError):
            pass
    # macOS accepts RLIMIT_AS but does not enforce it: watch the peak resident
    # size instead (bytes on macOS, KiB elsewhere).
    unit = 1 if sys.platform == "darwin" else 1024

    def watch() -> None:
        import time

        while resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * unit <= limit:
            time.sleep(0.005)
        os._exit(_OVER_MEMORY)

    threading.Thread(target=watch, daemon=True).start()
