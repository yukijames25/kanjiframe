"""Mainframe numeric formats: packed decimal (COMP-3), zoned decimal (DISPLAY), binary (COMP).

All functions use Decimal so that PIC S9(13)V99 amounts keep every digit. Errors are raised as
NumberError with a message a person can act on (which byte, what was expected).
"""
from __future__ import annotations

from decimal import Decimal

POSITIVE = {0xC, 0xF, 0xA, 0xE}
NEGATIVE = {0xD, 0xB}


class NumberError(ValueError):
    pass


def _scaled(digits: str, scale: int, negative: bool) -> Decimal:
    value = Decimal(int(digits or "0")).scaleb(-scale)
    return -value if negative else value


# ---- packed decimal ------------------------------------------------------------
def unpack(data: bytes, scale: int = 0) -> Decimal:
    """COMP-3: two digits per byte, sign in the last nibble (C/F positive, D negative)."""
    if not data:
        raise NumberError("empty packed field")
    digits = []
    for i, b in enumerate(data):
        hi, lo = b >> 4, b & 0xF
        if hi > 9:
            raise NumberError(f"byte {i} ({b:02X}): {hi:X} is not a digit")
        digits.append(str(hi))
        if i < len(data) - 1:
            if lo > 9:
                raise NumberError(f"byte {i} ({b:02X}): {lo:X} is not a digit")
            digits.append(str(lo))
        elif lo not in POSITIVE | NEGATIVE:
            raise NumberError(f"last byte ({b:02X}): sign nibble {lo:X} is not C, D or F")
    return _scaled("".join(digits), scale, (data[-1] & 0xF) in NEGATIVE)


def pack(value, length: int, scale: int = 0, signed: bool = True) -> bytes:
    """Encode to COMP-3 of *length* bytes (2*length-1 digits)."""
    digits, negative = _digits(value, scale)
    room = 2 * length - 1
    if len(digits) > room:
        raise NumberError(f"{value} needs {len(digits)} digits; the field holds {room}")
    if negative and not signed:
        raise NumberError(f"{value} is negative but the field is unsigned")
    s = digits.rjust(room, "0") + ("D" if negative else ("C" if signed else "F"))
    return bytes.fromhex(s)


# ---- zoned decimal -------------------------------------------------------------
def unzone(data: bytes, scale: int = 0) -> Decimal:
    """DISPLAY numeric in EBCDIC: F0..F9, the last byte's zone carries the sign (C+, D-, F unsigned)."""
    if not data:
        raise NumberError("empty zoned field")
    digits = []
    for i, b in enumerate(data):
        zone, d = b >> 4, b & 0xF
        if d > 9:
            raise NumberError(f"byte {i} ({b:02X}) is not a digit")
        if i < len(data) - 1 and zone != 0xF:
            if b == 0x40:
                raise NumberError(f"byte {i} is a space (40), not a digit: the field may be blank or left-aligned")
            raise NumberError(f"byte {i} ({b:02X}) is not a digit")
        digits.append(str(d))
    sign = data[-1] >> 4
    if sign not in POSITIVE | NEGATIVE:
        raise NumberError(f"last byte ({data[-1]:02X}): zone {sign:X} is not C, D or F")
    return _scaled("".join(digits), scale, sign in NEGATIVE)


def zone(value, length: int, scale: int = 0, signed: bool = True) -> bytes:
    digits, negative = _digits(value, scale)
    if len(digits) > length:
        raise NumberError(f"{value} needs {len(digits)} digits; the field holds {length}")
    if negative and not signed:
        raise NumberError(f"{value} is negative but the field is unsigned")
    digits = digits.rjust(length, "0")
    out = bytearray(0xF0 | int(d) for d in digits)
    if signed:
        out[-1] = (0xD0 if negative else 0xC0) | int(digits[-1])
    return bytes(out)


# ---- binary --------------------------------------------------------------------
def unbin(data: bytes, scale: int = 0, signed: bool = True) -> Decimal:
    return Decimal(int.from_bytes(data, "big", signed=signed)).scaleb(-scale)


def binary(value, length: int, scale: int = 0, signed: bool = True) -> bytes:
    digits, negative = _digits(value, scale)
    n = -int(digits) if negative else int(digits)
    try:
        return n.to_bytes(length, "big", signed=signed)
    except OverflowError:
        raise NumberError(f"{value} does not fit in {length} bytes") from None


def binary_length(digits: int) -> int:
    """PIC 9(1-4) COMP = 2 bytes, 9(5-9) = 4, 9(10-18) = 8."""
    return 2 if digits <= 4 else 4 if digits <= 9 else 8


def _digits(value, scale: int) -> tuple[str, bool]:
    try:
        d = Decimal(str(value).replace(",", "").strip())
    except Exception:
        raise NumberError(f"{value!r} is not a number") from None
    if d != d.quantize(Decimal(1).scaleb(-scale)):
        raise NumberError(f"{value} has more than {scale} decimal places")
    q = int(d.scaleb(scale))
    return str(abs(q)), q < 0
