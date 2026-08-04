"""DPAPI do Windows via ``ctypes`` — sem dependência extra.

``CryptProtectData`` cifra com uma chave derivada da conta do usuário nesta
máquina: o blob não decifra em outra conta nem em outro computador. É o
equivalente Windows do ``systemd-creds --user`` do Linux.

Este módulo só importa em Windows; em outros sistemas o
:mod:`mfit2keep.secrets_store` nem chega a carregá-lo.
"""

import base64
import ctypes
from ctypes import wintypes


class _Blob(ctypes.Structure):
    """``DATA_BLOB``: par (tamanho, ponteiro) que a API usa para entrada e saída."""

    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(_Blob),
    wintypes.LPCWSTR,
    ctypes.POINTER(_Blob),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_Blob),
]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_Blob),
    ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(_Blob),
    ctypes.c_void_p,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(_Blob),
]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL

#: Sem prompt de UI: o app roda em terminal e em tarefa agendada.
_CRYPTPROTECT_UI_FORBIDDEN = 0x01


class DpapiError(RuntimeError):
    """A API do Windows recusou a operação."""


def _as_blob(data: bytes) -> _Blob:
    buffer = ctypes.create_string_buffer(data, len(data))
    return _Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char)))


def _read_and_free(blob: _Blob) -> bytes:
    """Copia o resultado e devolve a memória que a API alocou."""
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        _kernel32.LocalFree(blob.pbData)


def protect(value: str, *, entropy: str) -> str:
    """Cifra ``value``, devolvendo base64 de uma linha só.

    A entropia entra na derivação da chave: um blob cifrado com um nome não
    decifra com outro, do mesmo jeito que o ``--name`` do systemd-creds.
    """
    result = _Blob()
    ok = _crypt32.CryptProtectData(
        ctypes.byref(_as_blob(value.encode("utf-8"))),
        f"{entropy} (mfit2keep)",
        ctypes.byref(_as_blob(entropy.encode("utf-8"))),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    )
    if not ok:
        raise DpapiError(f"CryptProtectData falhou (erro {ctypes.get_last_error()}).")
    return base64.b64encode(_read_and_free(result)).decode("ascii")


def unprotect(blob: str, *, entropy: str) -> str:
    """Recupera o segredo. O blob em si não é sigiloso."""
    try:
        raw = base64.b64decode(blob, validate=True)
    except ValueError as error:
        raise DpapiError(f"Blob não é base64 válido: {error}") from error

    result = _Blob()
    ok = _crypt32.CryptUnprotectData(
        ctypes.byref(_as_blob(raw)),
        None,
        ctypes.byref(_as_blob(entropy.encode("utf-8"))),
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(result),
    )
    if not ok:
        raise DpapiError(
            f"CryptUnprotectData falhou (erro {ctypes.get_last_error()}). "
            "O blob foi cifrado em outra máquina, por outro usuário, ou com outro nome."
        )
    return _read_and_free(result).decode("utf-8")
