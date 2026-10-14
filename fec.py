"""Small systematic Reed-Solomon-style erasure code over GF(256).

This is deliberately dependency-free.  It handles variable final-packet sizes
by padding inside a block; callers trim recovered data to the logged size.
"""

from __future__ import annotations

PRIMITIVE_POLYNOMIAL = 0x11D
_EXP = [0] * 512
_LOG = [0] * 256
_x = 1
for _i in range(255):
    _EXP[_i] = _x
    _LOG[_x] = _i
    _x <<= 1
    if _x & 0x100:
        _x ^= PRIMITIVE_POLYNOMIAL
for _i in range(255, 512):
    _EXP[_i] = _EXP[_i - 255]


def gf_mul(a: int, b: int) -> int:
    if a == 0 or b == 0:
        return 0
    return _EXP[_LOG[a] + _LOG[b]]


def gf_inv(a: int) -> int:
    if a == 0:
        raise ZeroDivisionError("zero has no multiplicative inverse")
    return _EXP[255 - _LOG[a]]


def coefficients(parity_index: int, k: int) -> list[int]:
    """Return a Cauchy row for the requested parity packet.

    Every square submatrix of a Cauchy matrix is invertible, so any m lost data
    packets can be rebuilt from any m parity packets (an MDS code). A plain
    Vandermonde row over GF(256) does not guarantee this: some 3- and 4-packet
    loss patterns were unrecoverable even with enough parity (and crashed the
    receiver). Needs k <= 16 and parity_index < 240 so x and y never collide.
    """
    x = 16 + parity_index
    return [gf_inv(x ^ column) for column in range(k)]


def encode(data_packets: list[bytes], r: int) -> list[bytes]:
    if not data_packets or r <= 0:
        return []
    width = max(map(len, data_packets))
    padded = [packet.ljust(width, b"\0") for packet in data_packets]
    result: list[bytes] = []
    for parity_index in range(r):
        row = coefficients(parity_index, len(padded))
        output = bytearray(width)
        for coefficient, packet in zip(row, padded):
            for position, value in enumerate(packet):
                output[position] ^= gf_mul(coefficient, value)
        result.append(bytes(output))
    return result


def _invert(matrix: list[list[int]]) -> list[list[int]]:
    size = len(matrix)
    augmented = [row[:] + [int(i == j) for j in range(size)] for i, row in enumerate(matrix)]
    for column in range(size):
        pivot = next((row for row in range(column, size) if augmented[row][column]), None)
        if pivot is None:
            raise ValueError("singular recovery matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = gf_inv(augmented[column][column])
        augmented[column] = [gf_mul(value, scale) for value in augmented[column]]
        for row in range(size):
            if row == column or augmented[row][column] == 0:
                continue
            factor = augmented[row][column]
            augmented[row] = [
                left ^ gf_mul(factor, right)
                for left, right in zip(augmented[row], augmented[column])
            ]
    return [row[size:] for row in augmented]


def recover(
    data_packets: list[bytes | None], parity_packets: dict[int, bytes]
) -> dict[int, bytes]:
    """Recover missing data positions; return an empty dict if impossible."""
    missing = [index for index, packet in enumerate(data_packets) if packet is None]
    if not missing:
        return {}
    chosen = sorted(parity_packets)[: len(missing)]
    if len(chosen) < len(missing):
        return {}
    width = max(len(parity_packets[index]) for index in chosen)
    equations: list[bytearray] = []
    matrix: list[list[int]] = []
    for parity_index in chosen:
        row = coefficients(parity_index, len(data_packets))
        value = bytearray(parity_packets[parity_index].ljust(width, b"\0"))
        for data_index, packet in enumerate(data_packets):
            if packet is None:
                continue
            for position, byte in enumerate(packet.ljust(width, b"\0")):
                value[position] ^= gf_mul(row[data_index], byte)
        matrix.append([row[index] for index in missing])
        equations.append(value)
    inverse = _invert(matrix)
    recovered: dict[int, bytes] = {}
    for result_row, data_index in zip(inverse, missing):
        output = bytearray(width)
        for coefficient, equation in zip(result_row, equations):
            for position, value in enumerate(equation):
                output[position] ^= gf_mul(coefficient, value)
        recovered[data_index] = bytes(output)
    return recovered
