"""Persistent claude.ai sessionKey storage, encrypted with Windows DPAPI.

We never put the raw cookie on disk. CryptProtectData binds the ciphertext to
the current user account — anyone else logging into this machine cannot
decrypt it, and neither can this user from a different box.
"""

from __future__ import annotations

import ctypes
from ctypes import POINTER, byref, c_char, c_void_p, wintypes

from .config import CONFIG_DIR

SESSION_PATH = CONFIG_DIR / "claude_session.dat"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", POINTER(c_char))]


# Declaring argtypes / restype is critical on 64-bit Windows. Without them,
# ctypes assumes int-sized arguments and the kernel pointer args get
# truncated, causing access violations.
_crypt32 = ctypes.windll.crypt32
_kernel32 = ctypes.windll.kernel32

_crypt32.CryptProtectData.argtypes = [
    POINTER(_DataBlob),    # pDataIn
    wintypes.LPCWSTR,      # szDataDescr
    POINTER(_DataBlob),    # pOptionalEntropy
    c_void_p,              # pvReserved
    c_void_p,              # pPromptStruct
    wintypes.DWORD,        # dwFlags
    POINTER(_DataBlob),    # pDataOut
]
_crypt32.CryptProtectData.restype = wintypes.BOOL

_crypt32.CryptUnprotectData.argtypes = [
    POINTER(_DataBlob),
    POINTER(wintypes.LPWSTR),  # ppszDataDescr (not used; pass None)
    POINTER(_DataBlob),
    c_void_p,
    c_void_p,
    wintypes.DWORD,
    POINTER(_DataBlob),
]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL

_kernel32.LocalFree.argtypes = [c_void_p]
_kernel32.LocalFree.restype = c_void_p


def _make_input_blob(data: bytes) -> _DataBlob:
    buf = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob()
    blob.cbData = len(data)
    blob.pbData = ctypes.cast(buf, POINTER(c_char))
    blob._buf = buf  # type: ignore[attr-defined]  # keep buffer alive
    return blob


def _read_output_blob(blob: _DataBlob) -> bytes:
    if not blob.pbData:
        return b""
    out = ctypes.string_at(blob.pbData, blob.cbData)
    _kernel32.LocalFree(blob.pbData)
    return out


def _dpapi_protect(data: bytes) -> bytes:
    in_blob = _make_input_blob(data)
    out_blob = _DataBlob()
    ok = _crypt32.CryptProtectData(
        byref(in_blob), None, None, None, None, 0, byref(out_blob)
    )
    if not ok:
        raise OSError(f"CryptProtectData failed (GetLastError={ctypes.GetLastError()})")
    return _read_output_blob(out_blob)


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob = _make_input_blob(data)
    out_blob = _DataBlob()
    ok = _crypt32.CryptUnprotectData(
        byref(in_blob), None, None, None, None, 0, byref(out_blob)
    )
    if not ok:
        raise OSError(f"CryptUnprotectData failed (GetLastError={ctypes.GetLastError()})")
    return _read_output_blob(out_blob)


def save_session_key(value: str) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_bytes(_dpapi_protect(value.encode("utf-8")))


def load_session_key() -> str | None:
    if not SESSION_PATH.exists():
        return None
    try:
        return _dpapi_unprotect(SESSION_PATH.read_bytes()).decode("utf-8")
    except OSError:
        return None


def clear_session_key() -> None:
    try:
        SESSION_PATH.unlink()
    except FileNotFoundError:
        pass
