"""One UHD 59.94 LongGOP 400Mbps ceiling, via the guarded owned-page runner.

Default is offline preflight. No setting selection or recording command. The
FPS/resource fixes must already be present; operate only in idle 29.97/200.
"""
import struct

import normal_fps_patch as shared

TARGET, ORIGINAL, REPLACEMENT, MAGIC = 0x013E13C4, 1, 0, 0x42525431


def guard_idle_30p(p):
    if p.read(0x02CDDE60, 2) != b'\2\7' or p.read(0x02E94A30, 1) != b'\7':
        raise RuntimeError('Bitrate operation requires idle original 30p profile')
    roots = p.read(0x02E137E8, 8)
    if any(v not in (0, 0xFFFFFFFF) for v in struct.unpack('<2I', roots)):
        raise RuntimeError('Recording context remains active')
    settings = p.read(0x0177F8C0, 164)
    if any(settings[o] != v for o, v in ((0x2B, 0), (0x2D, 3), (0x74, 1),
                                        (0x75, 0), (0x90, 1), (0xA1, 1))):
        raise RuntimeError('Require UHD 29.97 MOV/H264 LongGOP 200 before bitrate operation')
    if p.read(0x01B85AD2, 1) != b'\4':
        raise RuntimeError('Cached native frame rate differs from 29.97')
    if (p.read(0x013E1788, 4) != shared.word(0x7FFFFFFE)
            or p.read(0x02219ED0, 4) != shared.word(0xE3A00006)):
        raise RuntimeError('Validated FPS and independent-buffer fixes must be present')
    if p.read(0x0011C088, 4) != shared.word(0x0221EC06):
        raise RuntimeError('Backend code section is not RX')
    image = (shared.SOURCE / 'XT30II_FW204_section_00260060.bin').read_bytes()
    if p.read(0x01027778, 124) != image[0x6778:0x67F4]:
        raise RuntimeError('Native bitrate wrapper fingerprint differs')
    return settings, roots


POLICY = shared.RulePolicy('normal_bitrate', TARGET, ORIGINAL, REPLACEMENT,
                          MAGIC, 0x013E1388, 872, guard_idle_30p)


if __name__ == '__main__':
    raise SystemExit(shared.main(POLICY, __doc__))
