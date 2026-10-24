"""Lector mínimo de capturas pcap para contar Beacons (sin dependencias)."""

from __future__ import annotations

import struct
from pathlib import Path

PCAP_MAGIC_LE = 0xA1B2C3D4
PCAP_MAGIC_BE = 0xD4C3B2A1
PCAP_MAGIC_NS_LE = 0xA1B23C4D
PCAP_MAGIC_NS_BE = 0x4D3CB2A1


def count_beacons(path: Path) -> dict[str, int]:
    try:
        data = path.read_bytes()
    except OSError:
        return {"packets": 0, "beacons": 0}
    if len(data) < 24:
        return {"packets": 0, "beacons": 0}
    magic = struct.unpack("<I", data[:4])[0]
    if magic in (PCAP_MAGIC_LE, PCAP_MAGIC_NS_LE):
        endian = "<"
    elif magic in (PCAP_MAGIC_BE, PCAP_MAGIC_NS_BE):
        endian = ">"
    else:
        return {"packets": 0, "beacons": 0}
    linktype = struct.unpack(endian + "I", data[20:24])[0]
    offset = 24
    packets = 0
    beacons = 0
    while offset + 16 <= len(data):
        _, _, incl_len, _ = struct.unpack(endian + "IIII", data[offset : offset + 16])
        offset += 16
        if incl_len <= 0 or offset + incl_len > len(data):
            break
        frame = data[offset : offset + incl_len]
        offset += incl_len
        packets += 1
        if linktype == 127 and len(frame) > 4:
            radiotap_len = struct.unpack("<H", frame[2:4])[0]
            if 0 < radiotap_len < len(frame):
                frame = frame[radiotap_len:]
        if len(frame) >= 2:
            frame_control = frame[0]
            frame_type = (frame_control >> 2) & 0x03
            subtype = (frame_control >> 4) & 0x0F
            if frame_type == 0 and subtype == 8:
                beacons += 1
    return {"packets": packets, "beacons": beacons}
