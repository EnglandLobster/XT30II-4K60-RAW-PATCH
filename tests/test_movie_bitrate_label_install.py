"""Failure injection into the compiled Jig installer, never a USB session.

The full successful loader/MMU execution is checked by verify_loader_probe.
Here allocation and protection return values are controlled to test rejection.
"""
from pathlib import Path
import json
import struct
import sys
import unittest

from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_PC, UC_ARM_REG_LR

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from emulation_support import machine, call
from verify_loader_probe import SCRATCH, L1, OUT, TABLE, build_page
from research_fixtures import cold_capture as capture
from movie_bitrate_label import FONT_WINDOW, font_reference, CHANGES


class LabelInstallTests(unittest.TestCase):
    def run_case(self, failure):
        uc = machine()
        uc.mem_map(SCRATCH, 4096)
        uc.mem_write(SCRATCH, build_page(capture(TABLE,396), 'rec_install_label_probe'))
        uc.mem_write(FONT_WINDOW, font_reference())
        uc.mem_write(L1+0x1c*4, struct.pack('<I',0xa0401))
        uc.mem_write(0xa0400, capture(0xa0400,1024))
        for index, descriptor in ((0x25,0x0251ec16),(0x22,0x0221ec06),(0x3e,0x03e16c06)):
            uc.mem_write(L1+index*4,struct.pack('<I',descriptor))
        uc.mem_write(0x01b7b518,b'\x0c')
        uc.mem_write(0x01b6a020,b'\x07')
        if failure=='not_jig': uc.mem_write(0x01b7b518,b'\3')
        if failure=='backend': uc.mem_write(0x01b6a020,b'\1')
        if failure=='prologue': uc.mem_write(CHANGES[0][0],bytes(4))
        if failure=='abi': uc.mem_write(SCRATCH+0x3c4,bytes(4))
        calls, writes = [], []
        targets={x[0] for x in CHANGES}
        def hook(emu,address,size,_):
            a,b,c=[emu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]
            if address==0x013d77a4:
                calls.append(('allocate',a))
                emu.reg_write(UC_ARM_REG_R0,0x01c1df10 if failure=='allocation_address' else 0x01c1cf10)
            elif address==0x013d77c4:
                calls.append(('free',a)); emu.reg_write(UC_ARM_REG_R0,0)
            elif address==0x0128bc9c:
                calls.append(('protect',a,b,c))
                fail=((failure=='label_write' and a==0x01c1d000 and c==7)
                      or (failure=='label_rx' and a==0x01c1d000 and c==5
                          and sum(x==('protect',a,b,c) for x in calls)>1)
                      or (failure=='graphics_rx' and a==0x03e00000 and c==5)
                      or (failure=='graphics_restore' and a==0x03e00000 and c==7))
                emu.reg_write(UC_ARM_REG_R0,0xffffffef if fail else 0)
                if not fail:
                    if 0x01c00000<=a<0x01d00000:
                        descriptor=a|{3:0x5b7,5:0x7b6,7:0x5b6}[c]
                        emu.mem_write(0xa0400+((a>>12)&255)*4,struct.pack('<I',descriptor))
                    else:
                        descriptor=a|{1:0x1ec16,3:0x16c16,5:0x1ec06,7:0x16c06}[c]
                        emu.mem_write(L1+(a>>20)*4,struct.pack('<I',descriptor))
            else:
                return
            emu.reg_write(UC_ARM_REG_PC,emu.reg_read(UC_ARM_REG_LR))
        def write(emu,access,address,size,value,_):
            if address in targets:
                self.assertEqual(bytes(emu.mem_read(0x01b7b518,1)),b'\x0c')
                self.assertEqual(size,4)
                writes.append((address,value))
        uc.hook_add(UC_HOOK_CODE,hook)
        uc.hook_add(UC_HOOK_MEM_WRITE,write)
        manifest=json.loads((OUT/'build_manifest.json').read_text())
        entry=next(x for x in manifest if x['name']=='rec_install_label_probe')['symbols']['bootstrap_main']
        call(uc,entry,count=200000)
        result=struct.unpack('<8I',uc.mem_read(SCRATCH+0x1c0,32))
        return result,calls,writes

    def test_invalid_cold_baseline_publishes_nothing(self):
        for failure in ('not_jig','backend','prologue','abi'):
            with self.subTest(failure=failure):
                result,calls,writes=self.run_case(failure)
                self.assertEqual(result[1],0x80000020)
                self.assertEqual(calls,[])
                self.assertEqual(writes,[])

    def test_unexpected_allocation_never_publishes_label(self):
        result,calls,writes=self.run_case('allocation_address')
        self.assertEqual(result[1],0x80000022)
        self.assertEqual(writes,[])

    def test_code_protection_failures_never_publish_label(self):
        for failure,status in (('label_write',0x80000023),('label_rx',0x80000024)):
            with self.subTest(failure=failure):
                result,_,writes=self.run_case(failure)
                self.assertEqual(result[1],status)
                self.assertEqual(writes,[])

    def test_cache_permission_failures_are_not_reported_as_success(self):
        for failure in ('graphics_rx','graphics_restore'):
            with self.subTest(failure=failure):
                result,_,writes=self.run_case(failure)
                self.assertEqual(result[1],0x80000026)
                self.assertEqual(len(writes),4)

    def test_success_publishes_only_the_two_verified_prologues(self):
        result,calls,writes=self.run_case(None)
        self.assertEqual(result,(0x4c414231,2,0,0,4,0,0,0x03e16c06))
        self.assertEqual(dict(writes),{a:new for a,old,new in CHANGES})
        self.assertFalse(any(x[0]=='free' for x in calls))


if __name__=='__main__':
    unittest.main()
