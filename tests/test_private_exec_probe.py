"""Execute the compiled ownership/error paths; never import a USB library."""
from pathlib import Path
import struct
import unittest

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2,
    UC_ARM_REG_PC, UC_ARM_REG_LR, UC_ARM_REG_SP, UC_ARM_REG_CPSR)

ROOT = Path(__file__).resolve().parents[1]
ENTRY, REPORT, PAGE, RAW = 0x06b95400, 0x06b95180, 0x01c11000, 0x01c10120
STOP = 0x09010000


class PrivateExecutionFailureTests(unittest.TestCase):
    def run_case(self, failure=None):
        uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        for address, size in ((0x0011c000,0x4000),(0x00e20000,0x1000),
                              (0x01000000,0x01000000),(0x06b95000,0x1000),(0x09000000,0x20000)):
            uc.mem_map(address, size)
        uc.mem_write(ENTRY, (ROOT/'src/normal_route_20261012/private_exec_probe.bin').read_bytes())
        uc.mem_write(0x0011c070, struct.pack('<I',0x01c1ec16 if failure == 'mapping' else 0x01c16c16))
        calls, executed = [], []
        def hook(emu, address, size, _):
            args = [emu.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2)]
            value = 0
            if address == PAGE:
                executed.append(address)
                return
            if address == 0x013d77a4:
                calls.append(('allocate',args[0]))
                value = 0 if failure == 'allocate' else RAW
            elif address == 0x013d77c4:
                calls.append(('free',args[0]))
            elif address == 0x0128bc9c:
                calls.append(('protect',tuple(args)))
                if args[0] == PAGE and ((failure == 'protect' and args[2] == 5) or
                                       (failure == 'restore' and args[2] == 3)):
                    value = 0xffffffef
            else:
                return
            emu.reg_write(UC_ARM_REG_R0, value)
            emu.reg_write(UC_ARM_REG_PC, emu.reg_read(UC_ARM_REG_LR))
        uc.hook_add(UC_HOOK_CODE,hook)
        uc.reg_write(UC_ARM_REG_CPSR,0x13)
        uc.reg_write(UC_ARM_REG_SP,0x0900fff0)
        uc.reg_write(UC_ARM_REG_LR,STOP)
        uc.emu_start(ENTRY,STOP,count=10000)
        self.assertEqual(uc.reg_read(UC_ARM_REG_PC),STOP)
        self.assertEqual(uc.reg_read(UC_ARM_REG_SP),0x0900fff0)
        self.assertEqual(calls[-1],('protect',(0x06b95000,4096,3)))
        self.assertEqual(bytes(uc.mem_read(0x00e20000,4)),struct.pack('<I',0x00e20040))
        self.assertEqual(bytes(uc.mem_read(0x01780594,4)),bytes(4))
        return struct.unpack('<10I',uc.mem_read(REPORT,40)),calls,executed

    def test_success_executes_private_code_then_restores_before_free(self):
        result,calls,executed = self.run_case()
        self.assertEqual(result[1],2)
        self.assertEqual(result[7],0x51a7)
        self.assertEqual(executed,[PAGE])
        self.assertLess(calls.index(('protect',(PAGE,4096,3))),calls.index(('free',RAW)))

    def test_allocation_failure_never_changes_heap_permissions(self):
        result,calls,executed = self.run_case('allocate')
        self.assertEqual(result[1],0x80000001)
        self.assertEqual(len(calls),2)
        self.assertEqual(executed,[])

    def test_unexpected_mapping_frees_without_protection_change(self):
        result,calls,executed = self.run_case('mapping')
        self.assertEqual(result[1],0x80000003)
        self.assertEqual(calls[1],('free',RAW))
        self.assertEqual(executed,[])

    def test_protection_error_does_not_execute_or_free_unknown_mapping(self):
        result,calls,executed = self.run_case('protect')
        self.assertEqual(result[1],0x80000004)
        self.assertFalse(any(c[0]=='free' for c in calls))
        self.assertEqual(executed,[])

    def test_restore_error_retains_memory_instead_of_returning_rx_heap(self):
        result,calls,executed = self.run_case('restore')
        self.assertEqual(result[1],0x80000005)
        self.assertFalse(any(c[0]=='free' for c in calls))
        self.assertEqual(executed,[PAGE])


if __name__ == '__main__':
    unittest.main()
