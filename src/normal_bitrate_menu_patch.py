"""Add a fourth bitrate choice to the two full movie menus in owned RAM.

The factory Q menu remains unchanged. The added row uses the ISO400 message ID
as a token. The optional movie_bitrate_label provider resolves it to 400Mbps
only inside the full movie menu; without that provider it is the native '400'.
Visual acceptance and actual encoder bitrate are separate.
No settings are selected, no recording is started, and no NVM command is sent.
"""
import struct

import normal_fps_patch as shared
from normal_bitrate_patch import guard_idle_30p

OUTPUT, VALUES, DISPLAY = 0x01C1F000, 0x01C1F040, 0x01C1F080
OUTPUT_SIZE, MAGIC = 0x180, 0x4D4E5531
REGION, REGION_SIZE = 0x01500000, 0x100000
L1_TARGET, RO, RW = 0x0011C054, 0x0151EC16, 0x01516C16
MENU_CURRENT = 0x01A405C4
# 01e29704 sets this byte on entry and clears it on exit. The root pointer
# intentionally remains cached after exit, so root == 0 is not a valid gate.
MENU_ACTIVE = 0x01A4117C
HEADERS = ((0x01525820, 0x01525740, 0x01525760),
           (0x01525E08, 0x01525D28, 0x01525D48))
CHANGES = tuple(change for header, values, display in HEADERS for change in (
    (header + 20, values, VALUES), (header + 24, display, DISPLAY)))


def build_output():
    image = (shared.SOURCE / 'XT30II_FW204_section_00260060.bin').read_bytes()
    def source(address, count):
        return image[address - 0x01021000:address - 0x01021000 + count]
    old_values = source(HEADERS[0][1], 32)
    old_display = source(HEADERS[0][2], 192)
    assert old_values == struct.pack('<8I', 1, 0, 2, 0, 3, 0, 0x7FFFFFFE, 0)
    assert old_display[-48:] == b'\xff' * 48
    assert source(HEADERS[1][1], 32) == old_values
    assert source(HEADERS[1][2], 192) == old_display
    for i, message in enumerate((0x926, 0x927, 0x928)):
        assert struct.unpack_from('<12I', old_display, i * 48) == (
            0x91F, 0, message, message, *([0] * 8))
    data = bytearray(OUTPUT_SIZE)
    struct.pack_into('<4I', data, 0, MAGIC, 1, 40, 240)
    data[0x48:0x68] = old_values
    data[0x80:0xB0] = old_display[:48]
    struct.pack_into('<2I', data, 0x88, 0x86C, 0x86C)
    data[0xB0:0x170] = old_display
    return bytes(data)


def guard_menu_closed(p):
    stable = guard_idle_30p(p)
    if p.read(0x013E13C4, 4) != shared.word(0):
        raise RuntimeError('400Mbps rule must already be installed')
    if p.read(L1_TARGET, 4) != shared.word(RO):
        raise RuntimeError('Menu section mapping does not match the compiled artifact')
    if p.read(shared.HEAP_L2 + 0x7C, 4) != shared.word(OUTPUT | 0x5B7):
        raise RuntimeError('Retained output page is not identity RW/XN')
    if p.read(MENU_ACTIVE, 1) != b'\0':
        raise RuntimeError('Native menu is active; exit menus before pointer changes')
    return stable


POLICY = shared.RulePolicy('normal_bitrate_menu', *CHANGES[0], MAGIC,
    0x01525740, 0x700, guard_menu_closed, REGION, REGION_SIZE,
    CHANGES[1:], (OUTPUT, build_output()))


if __name__ == '__main__':
    raise SystemExit(shared.main(POLICY, __doc__))
