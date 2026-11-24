"""Ed25519 (RFC 8032) in plain Python: signing a docs bundle when it is
published, and verifying it before nock shows it. Slow next to a C library
(a few milliseconds a signature), which a bundle checked once a run affords."""

from __future__ import annotations

import base64
import binascii
import hashlib

P = 2**255 - 19
L = 2**252 + 27742317777372353535851937790883648493
D = -121665 * pow(121666, P - 2, P) % P
SQRT_MINUS_ONE = pow(2, (P - 1) // 4, P)

type Point = tuple[int, int, int, int]


def sha512(data: bytes) -> int:
    return int.from_bytes(hashlib.sha512(data).digest(), "little")


def add(first: Point, second: Point) -> Point:
    x1, y1, z1, t1 = first
    x2, y2, z2, t2 = second
    a = (y1 - x1) * (y2 - x2) % P
    b = (y1 + x1) * (y2 + x2) % P
    c = 2 * t1 * t2 * D % P
    d = 2 * z1 * z2 % P
    e, f, g, h = b - a, d - c, d + c, b + a
    return (e * f % P, g * h % P, f * g % P, e * h % P)


def multiply(scalar: int, point: Point) -> Point:
    result: Point = (0, 1, 1, 0)
    while scalar:
        if scalar & 1:
            result = add(result, point)
        point = add(point, point)
        scalar >>= 1
    return result


def equal(first: Point, second: Point) -> bool:
    x1, y1, z1, _ = first
    x2, y2, z2, _ = second
    return (x1 * z2 - x2 * z1) % P == 0 and (y1 * z2 - y2 * z1) % P == 0


def recover_x(y: int, sign: int) -> int | None:
    if y >= P:
        return None
    x2 = (y * y - 1) * pow(D * y * y + 1, P - 2, P)
    if x2 == 0:
        return None if sign else 0
    x = pow(x2, (P + 3) // 8, P)
    if (x * x - x2) % P != 0:
        x = x * SQRT_MINUS_ONE % P
    if (x * x - x2) % P != 0:
        return None
    if (x & 1) != sign:
        x = P - x
    return x


BASE_Y = 4 * pow(5, P - 2, P) % P
BASE_X = recover_x(BASE_Y, 0) or 0
BASE: Point = (BASE_X, BASE_Y, 1, BASE_X * BASE_Y % P)


def compress(point: Point) -> bytes:
    x, y, z, _ = point
    inverse = pow(z, P - 2, P)
    x, y = x * inverse % P, y * inverse % P
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def decompress(data: bytes) -> Point | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    x = recover_x(y, sign)
    if x is None:
        return None
    return (x, y, 1, x * y % P)


def expand(seed: bytes) -> tuple[int, bytes]:
    digest = hashlib.sha512(seed).digest()
    scalar = int.from_bytes(digest[:32], "little")
    scalar &= (1 << 254) - 8
    scalar |= 1 << 254
    return scalar, digest[32:]


def public_key(seed: bytes) -> bytes:
    """The public key of the 32-byte private seed."""
    scalar, _ = expand(seed)
    return compress(multiply(scalar, BASE))


def sign(seed: bytes, message: bytes) -> bytes:
    """The 64-byte signature of `message` under the 32-byte private seed."""
    scalar, prefix = expand(seed)
    public = compress(multiply(scalar, BASE))
    nonce = sha512(prefix + message) % L
    encoded = compress(multiply(nonce, BASE))
    challenge = sha512(encoded + public + message) % L
    return encoded + int.to_bytes((nonce + challenge * scalar) % L, 32, "little")


def verify(public: bytes, message: bytes, signature: bytes) -> bool:
    """Whether `signature` is `message` signed by the holder of `public`."""
    if len(public) != 32 or len(signature) != 64:
        return False
    point = decompress(public)
    encoded = decompress(signature[:32])
    if point is None or encoded is None:
        return False
    scalar = int.from_bytes(signature[32:], "little")
    if scalar >= L:
        return False
    challenge = sha512(signature[:32] + public + message) % L
    return equal(multiply(scalar, BASE), add(encoded, multiply(challenge, point)))


def decoded(text: str, size: int) -> bytes | None:
    """`text` as standard base64 of exactly `size` bytes, or None."""
    try:
        raw = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError):
        return None
    return raw if len(raw) == size else None
