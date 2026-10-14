"""Wire format for data, parity, and feedback UDP datagrams.

The four-byte network-order integer is the JSON header length.  Payload bytes
follow it.  Keeping the header explicit makes Wireshark captures readable and
allows the receiver to validate every datagram before using it.
"""

from __future__ import annotations

import json
import struct
from typing import Any

HEADER_LENGTH = struct.Struct("!I")
MAX_HEADER_BYTES = 64 * 1024


class PacketError(ValueError):
    pass


def encode_packet(header: dict[str, Any], payload: bytes = b"") -> bytes:
    raw_header = json.dumps(header, separators=(",", ":")).encode("utf-8")
    if len(raw_header) > MAX_HEADER_BYTES:
        raise PacketError("header is too large")
    return HEADER_LENGTH.pack(len(raw_header)) + raw_header + payload


def decode_packet(datagram: bytes) -> tuple[dict[str, Any], bytes]:
    if len(datagram) < HEADER_LENGTH.size:
        raise PacketError("datagram is shorter than the length prefix")
    (header_size,) = HEADER_LENGTH.unpack_from(datagram)
    if header_size > MAX_HEADER_BYTES or len(datagram) < 4 + header_size:
        raise PacketError("invalid header length")
    try:
        header = json.loads(datagram[4 : 4 + header_size].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PacketError("invalid JSON header") from exc
    if not isinstance(header, dict) or "type" not in header:
        raise PacketError("header must be an object containing type")
    return header, datagram[4 + header_size :]
