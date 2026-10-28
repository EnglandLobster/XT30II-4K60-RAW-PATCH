"""Offline end-to-end dispatch of a RAM-only native-loader probe.

Runs original debug dispatcher, parser, loader, protection wrapper and kernel
page-table updater. RTOS synchronization and hardware cache/IPI operations
are stubbed explicitly; their real-world success is NOT established here.
"""
from pathlib import Path
import argparse
import hashlib
import json
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

ROOT = Path(__file__).resolve().parent
SOURCE, OUT = ROOT / "offline_20261011", ROOT / "normal_route_20261012"
SCRATCH, TABLE, CALLBACK, ROOT_PTR = 0x06B95000, 0x00E20040, 0x01780594, 0x00E20000
CLONE = SCRATCH + 0x200
LOADER, PROTECT = 0x0129CA08, 0x0128BC9C
L1, L2, PTE = 0x0011C000, 0x0009E800, 0x0009EA54
INPUT, STACK, STOP = 0x09000000, 0x0901FFF0, 0x09020000
INSTALL_PROBES = ('rec_install_probe', 'rec_install_label_probe')
PROBES = ('loader_probe', 'allocator_probe', 'private_exec_probe', *INSTALL_PROBES)


def capture(address, size):
    paths = sorted(SOURCE.glob(f"window_{address:08x}_*.bin"))
    for path in reversed(paths):
        data = path.read_bytes()
        if len(data) != size:
            continue
        report = json.loads(path.with_suffix(".json").read_text())
        if report["status"] != "success":
            raise ValueError(f"Unclean acquisition {path}")
        return data
    raise ValueError(f"Missing exact live capture {address:#x}/{size:#x}")


def build_page(table, payload_name="loader_probe"):
    if len(table) != 396 or table[-36:] != struct.pack("<9I", 255, *([0] * 8)):
        raise ValueError("Unexpected descriptor list")
    ids = [struct.unpack_from("<I", table, i)[0] for i in range(0, 396, 36)]
    if ids != [0, 1, 2, 9, 3, 4, 5, 6, 7, 8, 255]:
        raise ValueError("Unexpected descriptor IDs")
    clone = bytearray(table)
    if struct.unpack_from("<II", clone, 7 * 36 + 4) != (0x01E12000, 0x008D9000):
        raise ValueError("Unexpected module 6 mapping")
    struct.pack_into("<II", clone, 7 * 36 + 4, SCRATCH, 0x1000)
    if payload_name not in PROBES:
        raise ValueError("Unknown probe payload")
    code = (OUT / f"{payload_name}.bin").read_bytes()
    page = bytearray(0x1000)
    if payload_name == 'private_exec_probe' or payload_name in INSTALL_PROBES:
        limit = 0x800 if payload_name == 'rec_install_label_probe' else 0x600 if payload_name in INSTALL_PROBES else 0xc00
        if not code or len(code) > limit:
            raise ValueError("Private probe does not fit scratch page")
        struct.pack_into("<4I", page, 0, 0, SCRATCH, 0x1000, SCRATCH + 0x400)
        page[0x400:0x400+len(code)] = code
        if payload_name in INSTALL_PROBES:
            hook = (OUT/'rec_lifecycle_hook.bin').read_bytes()
            needle = struct.pack('<I',0xdeadbeef)
            if len(hook)>0x600 or hook.count(needle)!=1:
                raise ValueError('Hook image or state relocation invalid')
            hook_start = 0xc00 if payload_name == 'rec_install_label_probe' else 0xa00
            if hook_start + len(hook) > len(page):
                raise ValueError('Hook image exceeds scratch page')
            page[hook_start:hook_start+len(hook)] = hook
            struct.pack_into('<2I',page,0x194,len(hook),hook.index(needle))
            item=next(x for x in json.loads((OUT/'build_manifest.json').read_text()) if x['name']=='rec_lifecycle_hook')
            if item['sha256']!=hashlib.sha256(hook).hexdigest():raise ValueError('Manifest mismatch')
            struct.pack_into('<I',page,0x1ac,item['symbols']['usb_attach_guard'])
            if payload_name == 'rec_install_label_probe':
                from movie_bitrate_label import blob
                label = blob()
                page[0x40:0x180] = label[:0x140]
                page[0x390:0x3d0] = label[0x1c0:0x200]
    else:
        if len(code) > 0x180 or struct.unpack_from("<I", code, 12)[0] != SCRATCH + 32:
            raise ValueError("Invalid probe image/header")
        page[:len(code)] = code
    page[0x200:0x200 + len(clone)] = clone
    return bytes(page)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--payload", choices=PROBES, default="loader_probe")
    payload_name = parser.parse_args().payload
    images = []
    for name, base in (("XT30II_FW204_kernel_00040000.bin", 0x40000),
                       ("XT30II_FW204_section_00260060.bin", 0x1021000),
                       ("XT30II_FW204_section_00600060.bin", 0x1E12000)):
        images.append((name, base, (SOURCE / name).read_bytes()))
    for address, size, image_index in ((0x0129C05C, 0x94, 1), (LOADER, 0x50, 1),
                                       (0x0128B9B0, 0x340, 1), (0x011898C4, 0x130, 1),
                                       (0x0209AA94, 0x2E8, 2), (0x00057DCC, 0x1134, 0)):
        _, base, data = images[image_index]
        if capture(address, size) != data[address-base:address-base+size]:
            raise ValueError(f"Live fingerprint mismatch {address:#x}")
    if payload_name in ('allocator_probe', 'private_exec_probe', *INSTALL_PROBES):
        _, base, data = images[1]
        if capture(0x013D77A4, 0x234C) != data[0x013D77A4-base:0x013D77A4-base+0x234C]:
            raise ValueError("Allocator code fingerprint mismatch")
    table = capture(TABLE, 396)
    root = capture(ROOT_PTR, 8)
    assert struct.unpack("<II", root) == (TABLE, 0x00E201EC)
    page = build_page(table, payload_name)
    original_l2 = capture(L2, 1024)
    original_pte = struct.unpack_from("<I", original_l2, PTE-L2)[0]
    assert original_pte == 0x06B955B7
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.mem_map(0x00040000, 0x001C0000)
    uc.mem_map(0x00E00000, 0x03200000)
    uc.mem_map(SCRATCH, 0x1000)
    uc.mem_map(INPUT, 0x30000)
    uc.mem_map(0x0A000000, 0x4000)
    uc.mem_write(0x0A000000, b"\xa5" * 0x4000)
    for _, base, data in images:
        uc.mem_write(base, data)
    uc.mem_write(L1 + 0x6B * 4, struct.pack("<I", L2 | 1))
    uc.mem_write(L2, original_l2)
    private = payload_name == "private_exec_probe"
    installing = payload_name in INSTALL_PROBES
    label_installing = payload_name == 'rec_install_label_probe'
    allocation = 0x01C1CF10 if installing else 0x01C10120 if private else 0x0A000120
    owned_page = (allocation + 4095) & ~4095
    if private:
        uc.mem_write(L1 + 0x1c*4, struct.pack("<I", 0x01C16C16))
    if installing:
        uc.mem_write(L1 + 0x1c*4,struct.pack('<I',0xa0401))
        uc.mem_write(0xa0400,capture(0xa0400,1024))
        uc.mem_write(L1 + 0x25*4,capture(L1+0x25*4,4))
        assert capture(L1+0x25*4,4)==struct.pack('<I',0x0251ec16)
        # Static expected section. The live installer checks this BEFORE staging.
        uc.mem_write(L1+0x22*4,struct.pack('<I',0x0221ec06))
    if label_installing:
        from movie_bitrate_label import FONT_WINDOW, font_reference
        uc.mem_write(FONT_WINDOW, font_reference())
        uc.mem_write(L1 + 0x3e * 4, struct.pack('<I', 0x03e16c06))
        uc.mem_write(0x01b7b518, b'\x0c')
        uc.mem_write(0x01b6a020, b'\x07')
    # No allocation should be needed: both boundaries already use 4 KiB pages.
    uc.mem_write(0x82CF4, struct.pack("<I", 11))
    uc.mem_write(TABLE, table)
    uc.mem_write(ROOT_PTR, struct.pack("<I", CLONE))
    uc.mem_write(CALLBACK, struct.pack("<I", LOADER))
    uc.mem_write(SCRATCH, page)
    calls, pt_writes, allocations = [], [], []
    stubs = {
        0x012893D8: "semaphore_lock", 0x01289428: "semaphore_unlock",
        0x0128BC70: "multicore_quiesce_and_clean",
        0x0128BA30: "task_affinity_restore",
        0x00058E9C: "cache_maintenance",
        0x00049218: "kernel_TLB_IPI",
        0x00058EB4: "instruction_cache_invalidate",
    }

    def hook(emu, address, size, _):
        r0, r1, r2 = [emu.reg_read(r) for r in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2)]
        if label_installing and address == 0x0128e39c:
            raise AssertionError(('unexpected native log', hex(emu.reg_read(UC_ARM_REG_LR)),
                [hex(v) for v in (r0,r1,r2)], allocations,
                bytes(emu.mem_read(SCRATCH+0x180,96)).hex(), calls[-12:]))
        if address == PROTECT:
            calls.append({"native_protect": [hex(r0), hex(r1), r2]})
        elif address == SCRATCH + (0x400 if private or installing else 32):
            assert struct.unpack("<I", emu.mem_read(PTE, 4))[0] == original_pte & ~1
            calls.append({"probe_entered_after_XN_clear": True})
        if address == 0x013D77A4 and payload_name in ('allocator_probe', 'private_exec_probe', *INSTALL_PROBES):
            assert r0 == (0x3000 if installing else 0x2000)
            allocations.append("allocated")
            emu.reg_write(UC_ARM_REG_R0, allocation)
        elif address == 0x013D77C4 and payload_name in ("allocator_probe", "private_exec_probe"):
            assert r0 == allocation and allocations == ["allocated"]
            if not private:
                assert bytes(emu.mem_read(owned_page, 4096)) == bytes(4096)
            allocations.append("freed")
            emu.reg_write(UC_ARM_REG_R0, 0)
        elif address == 0x01272D54:
            assert r0 == 0xF7
            emu.reg_write(UC_ARM_REG_R0, 1)
        elif address == 0x0128B9B0:
            calls.append({"stub": "task_affinity_save"})
            emu.mem_write(r0, struct.pack("<I", 1))
            emu.reg_write(UC_ARM_REG_R0, 0)
        elif address in stubs:
            calls.append({"stub": stubs[address]})
            emu.reg_write(UC_ARM_REG_R0, 0)
        else:
            return
        emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))

    def writes(emu, access, address, size, value, _):
        if 0x9c000 <= address < 0xa4000 or L1 <= address < L1 + 0x4000 or address == 0x82CF4:
            pt_writes.append({"address": hex(address), "size": size, "value": hex(value)})
            if not private and not installing:
                assert address == PTE and size == 4, "Unexpected page-table topology change"

    uc.hook_add(UC_HOOK_CODE, hook)
    uc.hook_add(UC_HOOK_MEM_WRITE, writes)
    payload = b"CMD X\n"
    request = bytearray(36) + payload
    struct.pack_into("<I", request, 0, 0x200001)
    struct.pack_into("<I", request, 16, 5)
    struct.pack_into("<I", request, 32, len(payload))
    uc.mem_write(INPUT, bytes(request))
    uc.reg_write(UC_ARM_REG_CPSR, 0x13)
    uc.reg_write(UC_ARM_REG_SP, STACK)
    uc.reg_write(UC_ARM_REG_LR, STOP)
    uc.reg_write(UC_ARM_REG_R0, INPUT)
    for i, reg in enumerate((UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                             UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)):
        uc.reg_write(reg, 0xA1000000 + i)
    uc.emu_start(0x0209AA94, STOP, count=1000000 if label_installing else 100000)
    assert uc.reg_read(UC_ARM_REG_PC) == STOP, (hex(uc.reg_read(UC_ARM_REG_PC)), calls[-6:])
    assert uc.reg_read(UC_ARM_REG_SP) == STACK
    for i, reg in enumerate((UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
                             UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11)):
        assert uc.reg_read(reg) == 0xA1000000 + i
    assert bytes(uc.mem_read(ROOT_PTR, 4)) == struct.pack("<I", TABLE)
    assert bytes(uc.mem_read(CALLBACK, 4)) == bytes(4)
    assert bytes(uc.mem_read(L2, 1024)) == original_l2
    assert bytes(uc.mem_read(TABLE, 396)) == table
    if not private and not installing:
        assert bytes(uc.mem_read(SCRATCH + 0x180, 4)) == struct.pack("<I", 0x50524F42)
    status = struct.unpack("<II", uc.mem_read(0x026ED068, 8))
    assert status == (0, 0)
    if payload_name == "allocator_probe":
        assert allocations == ["allocated", "freed"]
        assert struct.unpack("<3I", uc.mem_read(SCRATCH + 0x184, 12)) == (0x0A000120, 0x0A001000, 0xFEEEFEEE)
    if private:
        result = struct.unpack("<10I", uc.mem_read(SCRATCH+0x180, 40))
        assert result[:5] == (0x50525831, 2, allocation, owned_page, 0x01C16C16), result
        assert result[6:] == (0, 0x51a7, 0, 1), result
        assert allocations == ["allocated", "freed"]
        coarse = result[5] & ~0x3ff
        assert coarse == 0x9ec00
        # Every virtual 4 KiB page retains identity mapping and RW/XN;
        # stock API intentionally retains its newly allocated L2 table.
        l2_words = struct.unpack("<256I", uc.mem_read(coarse, 1024))
        for i, descriptor in enumerate(l2_words):
            virtual = 0x01c00000 + i*0x1000
            expected = ((virtual & ~0xffff) | 0xe435) if descriptor & 3 == 1 else (virtual | 0x5b7)
            assert descriptor == expected, (i,hex(descriptor))
            if descriptor & 3 == 1:
                assert l2_words[i & ~15:(i & ~15)+16] == (descriptor,)*16
        assert struct.unpack("<I", uc.mem_read(0x82cf4, 4))[0] == 12
        allowed = {PTE, L1 + 0x1c*4, 0x82cf4}
        assert all(int(w['address'],16) in allowed or coarse <= int(w['address'],16) < coarse+1024
                   for w in pt_writes)
    elif installing:
        result=struct.unpack('<16I',uc.mem_read(SCRATCH+0x180,64))
        hook=bytearray((OUT/'rec_lifecycle_hook.bin').read_bytes())
        offset=hook.index(struct.pack('<I',0xdeadbeef))
        guard_offset=struct.unpack_from('<I',page,0x1ac)[0]
        branch=0x0b000000|(((owned_page+guard_offset-0x02240d8c)>>2)&0xffffff)
        assert result==(0x52494e31,2,allocation,owned_page,owned_page+4096,len(hook),offset,0,0,0,1,
                        guard_offset,branch,0,0,1),result
        struct.pack_into('<I',hook,offset,owned_page+4096)
        assert bytes(uc.mem_read(owned_page,len(hook)))==bytes(hook)
        assert struct.unpack('<16I',uc.mem_read(owned_page+4096,64))==(
            0x52454348,2,allocation,owned_page,owned_page+4096,0,0,0,0,0,0x01e670d0,12,7,0,0,0)
        assert struct.unpack('<I',uc.mem_read(0x02581e78,4))[0]==owned_page
        assert bytes(uc.mem_read(L1+0x25*4,4))==struct.pack('<I',0x0251ec16)
        assert struct.unpack('<I',uc.mem_read(0xa0400+((owned_page>>12)&255)*4,4))[0]==owned_page|0x7b6
        assert allocations==['allocated']
        assert bytes(uc.mem_read(L1+0x22*4,4))==struct.pack('<I',0x0221ec06)
        assert bytes(uc.mem_read(0x02240d84,4))==struct.pack('<I',branch)
        allowed={PTE,L1+0x25*4,L1+0x22*4,0xa0400+((owned_page>>12)&255)*4}
        if label_installing:
            from movie_bitrate_label import blob, patched_window, FONT_WINDOW, FONT_SIZE
            assert bytes(uc.mem_read(owned_page+0x400,512)) == blob()
            assert bytes(uc.mem_read(FONT_WINDOW,FONT_SIZE)) == patched_window()
            assert struct.unpack('<8I',uc.mem_read(SCRATCH+0x1c0,32)) == (
                0x4c414231,2,0,0,4,0,0,0x03e16c06)
            assert bytes(uc.mem_read(L1+0x3e*4,4)) == struct.pack('<I',0x03e16c06)
            allowed.add(L1+0x3e*4)
        assert all(int(w['address'],16) in allowed for w in pt_writes)
    else:
        assert pt_writes == [{"address": hex(PTE), "size": 4, "value": hex(original_pte & ~1)},
                             {"address": hex(PTE), "size": 4, "value": hex(original_pte)}]
    report = {"camera_operations": 0, "status": "passed", "payload": payload_name, "dispatch_status": list(status),
              "scratch_page_sha256": hashlib.sha256(page).hexdigest(),
              "calls": calls, "page_table_writes": pt_writes,
              "restored_in_emulation": ["loader root", "CMD callback", "exact full L2 table",
                                        "callee-saved registers", "stack pointer"],
              "allocations": allocations,
              "private_execution": {"return": "0x51a7", "permissions_restored": True,
                                    "stock_coarse_table_retained": True} if private else None,
              "passive_hook_installation": {"enabled":False,"arena_bytes_retained":12288,
                                            "ui_table_permissions_restored":True} if installing else None,
              "limitations": "RTOS synchronization, affinity, cache and IPI operations are stubs; allocator probe also stubs malloc/free. No proof of live execution, SMP/cache behavior, normal shooting mode or camera rollback. Native loader loops forever on protection failure; do not auto-retry a live timeout."}
    (OUT / f"{payload_name}_page.bin").write_bytes(page)
    (OUT / f"{payload_name}_emulation.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
