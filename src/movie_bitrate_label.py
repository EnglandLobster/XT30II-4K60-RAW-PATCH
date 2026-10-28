"""Immutable layout and exact 2.06 evidence for the movie-menu label provider."""
from pathlib import Path
import hashlib
import struct

ROOT = Path(__file__).resolve().parent
OUT = ROOT / 'normal_route_20261012'
SOURCE = ROOT / 'offline_20261011'
FONT_WINDOW, FONT_SIZE = 0x03EB6600, 0x840
FONT_CAPTURE = 'window_03eb6600_20261012T132515505638Z.bin'
FONT_SHA256 = 'c6bccb4a5bd190c1c89c82852709b54e805886dfa3db2997c01bcd29832b6030'
CODE, SIZE, RESOURCE = 0x01C1D400, 512, 0x01C1D5C0
WIDTH, RECORD, TEXT, COUNT = 0x03EB6CBC, 0x03EB6D28, 0x03EB6D58, 0x03EB6A98
BANK_POINTER = 0x041ABF40
CHANGES = ((WIDTH, 0xE52DB004, 0xE51FF004),
           (WIDTH + 4, 0xE28DB000, CODE),
           (RECORD, 0xE52DB004, 0xE51FF004),
           (RECORD + 4, 0xE28DB000, CODE + 0x40))


def font_reference():
    data = (SOURCE / FONT_CAPTURE).read_bytes()
    if len(data) != FONT_SIZE or hashlib.sha256(data).hexdigest() != FONT_SHA256:
        raise ValueError('The independently acquired 2.06 font fingerprint changed')
    for address, expected, _ in CHANGES:
        if struct.unpack_from('<I', data, address - FONT_WINDOW)[0] != expected:
            raise ValueError('Unexpected 2.06 native prologue')
    return data


def blob():
    data = (OUT / 'movie_bitrate_label.bin').read_bytes()
    if len(data) != SIZE or any(data[0x140:0x1C0]):
        raise ValueError('Label resource does not fit the declared staging windows')
    if struct.unpack_from('<4I', data, 0x1E8) != (0x4C414231, WIDTH, RECORD, 0x206):
        raise ValueError('Label ABI/build marker mismatch')
    return data


def patched_window():
    data = bytearray(font_reference())
    for address, _, replacement in CHANGES:
        struct.pack_into('<I', data, address - FONT_WINDOW, replacement)
    return bytes(data)
