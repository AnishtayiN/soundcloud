"""Current-user Windows DPAPI credential vault; no plaintext fallback.

CryptProtectData is available on Windows 7 and later. The encrypted blob is
bound to the Windows account, with application-specific additional entropy.
Non-Windows development/test runs must inject a vault explicitly.
"""
from __future__ import annotations

import ctypes
import os
import sys
import tempfile

from .diagnostics import LOG

_ENTROPY = b"SoundCloudX.credentials.v1\0"


class CredentialError(Exception):
    pass


class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.c_uint32), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]


def _bytes(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob.pbData)


def _dpapi(data, encrypt):
    if sys.platform != "win32":
        raise CredentialError("Windows credential storage is unavailable on this platform")
    crypt = ctypes.windll.crypt32
    kernel = ctypes.windll.kernel32
    crypt.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), ctypes.c_wchar_p,
                                     ctypes.POINTER(_Blob), ctypes.c_void_p,
                                     ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.POINTER(ctypes.c_wchar_p),
                                       ctypes.POINTER(_Blob), ctypes.c_void_p,
                                       ctypes.c_void_p, ctypes.c_uint32, ctypes.POINTER(_Blob)]
    crypt.CryptProtectData.restype = ctypes.c_int
    crypt.CryptUnprotectData.restype = ctypes.c_int
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    source = _Blob(len(data), ctypes.cast(ctypes.create_string_buffer(data), ctypes.POINTER(ctypes.c_ubyte)))
    entropy = _Blob(len(_ENTROPY), ctypes.cast(ctypes.create_string_buffer(_ENTROPY), ctypes.POINTER(ctypes.c_ubyte)))
    output = _Blob()
    function = crypt.CryptProtectData if encrypt else crypt.CryptUnprotectData
    if not function(ctypes.byref(source), "SoundCloud X", ctypes.byref(entropy),
                    None, None, 0x01, ctypes.byref(output)):
        raise CredentialError("Windows credential protection failed (code %s)" % kernel.GetLastError())
    return _bytes(output)


def _atomic_write(path, data):
    """Write a credential blob without exposing a partially written vault."""
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".credentials-", suffix=".tmp", dir=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class CredentialVault(object):
    def __init__(self, path):
        self.path = path

    def get(self, key):
        import json
        try:
            with open(self.path, "rb") as stream:
                payload = _dpapi(stream.read(), False)
            values = json.loads(payload.decode("utf-8"))
            if not isinstance(values, dict):
                raise ValueError("invalid credential vault")
            return values.get(key, "")
        except FileNotFoundError:
            return ""
        except (OSError, IOError, ValueError, UnicodeError, CredentialError) as error:
            LOG.warning("credential vault load failed (%s)", type(error).__name__)
            raise CredentialError("credential vault is unavailable") from None

    def set(self, key, value):
        import json
        try:
            values = {}
            if os.path.exists(self.path):
                # Preserve other credentials only in memory, never as plaintext.
                with open(self.path, "rb") as stream:
                    values = json.loads(_dpapi(stream.read(), False).decode("utf-8"))
            values[key] = value or ""
            payload = json.dumps(values, ensure_ascii=False).encode("utf-8")
            _atomic_write(self.path, _dpapi(payload, True))
        except (OSError, IOError, ValueError, TypeError, CredentialError) as error:
            LOG.error("credential vault save failed (%s)", type(error).__name__)
            raise CredentialError("credential vault could not be saved") from None

    def delete(self, key):
        self.set(key, "")

    def clear(self):
        try:
            if os.path.exists(self.path):
                os.unlink(self.path)
        except (OSError, IOError) as error:
            LOG.error("credential vault removal failed (%s)", type(error).__name__)
            raise CredentialError("credential vault could not be cleared") from None
