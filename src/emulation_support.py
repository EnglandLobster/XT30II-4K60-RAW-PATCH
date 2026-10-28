"""Reusable original-image machine and ARM call boundary for offline tests.

Only RTOS synchronization, affinity, logging gate and hardware cache/IPI are
stubbed. This does not emulate sensor throughput, DMA timing or video quality.
"""
import hashlib
import json
import struct
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

from normal_resource_patch import *
from verify_loader_probe import INPUT, STACK, STOP, PROTECT, L1

BASELINE = OUT / "normal_fps_apply_20261012T063438626306Z"
IDLE = OUT / "movie_buffers_after_stop_request_20261012T064543530968Z"


def machine():
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    uc.mem_map(0x00040000, 0x001C0000)
    uc.mem_map(0x00E00000, 0x03200000)
    uc.mem_map(INPUT, 0x30000)
    for name, base in (("XT30II_FW204_kernel_00040000.bin", 0x40000),
                       ("XT30II_FW204_section_00260060.bin", 0x01021000),
                       ("XT30II_FW204_section_00600060.bin", 0x01E12000)):
        uc.mem_write(base, (SOURCE / name).read_bytes())
    return uc


def call(uc, entry, args=(), count=200000):
    for reg, value in ((UC_ARM_REG_CPSR, 0x13), (UC_ARM_REG_SP, STACK), (UC_ARM_REG_LR, STOP)):
        uc.reg_write(reg, value)
    for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        uc.reg_write(reg, value)
    uc.emu_start(entry, STOP, count=count)
    assert uc.reg_read(UC_ARM_REG_PC) == STOP, hex(uc.reg_read(UC_ARM_REG_PC))
    assert uc.reg_read(UC_ARM_REG_SP) == STACK
    return uc.reg_read(UC_ARM_REG_R0)
