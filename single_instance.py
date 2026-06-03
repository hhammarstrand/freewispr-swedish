"""
Single-instance-spärr (AP7.1).

Förhindrar två samtidiga instanser (dubbla hotkeys, två Whisper-modeller i VRAM
→ OOM, urklippskonflikt). Windows använder en namngiven mutex; andra plattformar
(och CI) faller tillbaka på att binda en fast loopback-port. Fail-open: om låset
inte kan tas av tekniska skäl blockerar vi inte starten.
"""
from __future__ import annotations

import logging
import sys

log = logging.getLogger("freewispr")

_MUTEX_NAME = "freewispr-swedish"
_LOOPBACK_PORT = 49731  # fast port; andra instansen får EADDRINUSE
_ERROR_ALREADY_EXISTS = 183

# Hålls vid liv under processens livstid så låset inte släpps av GC.
_handle = None


def acquire(name: str = _MUTEX_NAME) -> bool:
    """Return True if this process got the lock, False if one already holds it."""
    if sys.platform.startswith("win"):
        return _acquire_windows(name)
    return _acquire_socket()


def release() -> None:
    """Release the lock (call at app exit)."""
    global _handle
    h, _handle = _handle, None
    if h is None:
        return
    try:
        if sys.platform.startswith("win"):
            import ctypes
            from ctypes import wintypes
            close_handle = ctypes.windll.kernel32.CloseHandle
            close_handle.restype = wintypes.BOOL
            close_handle.argtypes = (wintypes.HANDLE,)
            close_handle(h)
        else:
            h.close()
    except Exception:
        pass


def _acquire_windows(name: str) -> bool:
    global _handle
    try:
        import ctypes
        from ctypes import wintypes
        # use_last_error=True so GetLastError() is captured into ctypes' own
        # per-call slot and read via ctypes.get_last_error(); calling
        # kernel32.GetLastError() separately is unreliable because the ctypes
        # machinery can clobber the thread error code between the two calls.
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Without explicit restype/argtypes ctypes assumes c_int and would
        # truncate the 64-bit HANDLE to 32 bits on Win64, corrupting the
        # handle we later pass to CloseHandle().
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateMutexW.argtypes = (
            wintypes.LPCVOID, wintypes.BOOL, wintypes.LPCWSTR,
        )
        kernel32.CloseHandle.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)

        handle = kernel32.CreateMutexW(None, False, name)
        if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
            # Another instance owns the mutex. Close our duplicate handle.
            try:
                kernel32.CloseHandle(handle)
            except Exception:
                pass
            return False
        _handle = handle
        return True
    except Exception as e:
        # Fail-open: never block startup because the lock primitive misbehaved.
        log.debug("Single-instance-mutex misslyckades (fail-open): %s", e)
        return True


def _acquire_socket() -> bool:
    global _handle
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # No SO_REUSEADDR — a second bind must fail while the first holds it.
        s.bind(("127.0.0.1", _LOOPBACK_PORT))
        s.listen(1)
        _handle = s
        return True
    except OSError:
        try:
            s.close()
        except Exception:
            pass
        return False
    except Exception as e:
        log.debug("Single-instance-socket misslyckades (fail-open): %s", e)
        try:
            s.close()
        except Exception:
            pass
        return True
