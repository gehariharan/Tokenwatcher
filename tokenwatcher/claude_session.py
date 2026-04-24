"""Persistent claude.ai sessionKey storage, encrypted with Windows DPAPI.

We never put the raw cookie on disk. CryptProtectData binds the ciphertext to
the current user account — anyone else logging into this machine cannot
decrypt it, and neither can this user from a different box.
"""

from __future__ import annotations

import ctypes
from ctypes import byref, c_char_p, wintypes
from pathlib import Path

from .config import CONFIG_DIR

SESSION_PATH = CONFIG_DIR / "claude_session.dat"


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", c_char_p)]


def _dpapi_protect(data: bytes) -> bytes:
    in_blob = _DataBlob(len(data), ctypes.cast(ctypes.c_char_p(data), c_char_p))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptProtectData(
        byref(in_blob), None, None, None, None, 0, byref(out_blob)
    )
    if not ok:
        raise OSError("CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


def _dpapi_unprotect(data: bytes) -> bytes:
    in_blob = _DataBlob(len(data), ctypes.cast(ctypes.c_char_p(data), c_char_p))
    out_blob = _DataBlob()
    ok = ctypes.windll.crypt32.CryptUnprotectData(
        byref(in_blob), None, None, None, None, 0, byref(out_blob)
    )
    if not ok:
        raise OSError("CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out_blob.pbData)


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
