"""Offline audit of stock movie resource descriptors; never opens a device.

Addresses come from the original resource allocator and its mode classifier,
not from a guessed search for repeated numbers. Descriptor words are retained
without assuming that firmware bus addresses equal CPU physical addresses.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import struct

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "offline_20261011"
MODELS = {
    "XT30II_FW204": {
        "file": "XT30II_FW204_section_00600060.bin", "base": 0x01E12000,
        "table": 0x025C0378, "row_width": 30, "profiles": (4, 5, 6, 7),
        "pools": {"MemResz": 27, "MemYcMv": 28, "alternate_yc": 29},
        "allocator": 0x02177B74, "set_mode": 0x021784E0,
    },
    "XT3_FW511": {
        "file": "XT3_FW511_section_00540060.bin", "base": 0x01B4E000,
        "table": 0x02229984, "row_width": 26, "profiles": (3, 4, 5, 6),
        "pools": {"MemResz": 23, "MemYcMv": 24, "alternate_yc": 25},
        "allocator": 0x01E6B8D4, "set_mode": 0x01E6C240,
    },
}

# These are bounded reference windows, not instructions to scan RAM. Verify
# the code/table bytes on 2.06 before interpreting the fixed globals below.
LIVE_FINGERPRINTS = (
    ("main_frame_copy_and_getters", "main", 0x012A0600, 0x900),
    ("main_route_input_getters", "main", 0x012A5300, 0x200),
    ("main_format_predicate", "main", 0x012AA280, 0x180),
    ("backend_resource_allocator", "backend", 0x02177988, 0x1098),
    ("backend_route_classifier", "backend", 0x02219D70, 0xA40),
    ("backend_active_context", "backend", 0x0221C80C, 0x7F4),
    ("resource_profile_rows", "backend", 0x025C0378, 8 * 30 * 8),
    ("four_k_descriptors", "backend", 0x025B34F8, 0x1050),
)
LIVE_FIXED_DATA = (
    ("frame_parameter_cache", 0x01B853F8, 0x478),
    ("route_parameter_cache", 0x01B85AB4, 0x478),
    ("resource_state_type_flags", 0x02CDDE60, 4),
    ("selected_resource_profile", 0x02E94A30, 1),
    ("active_context_roots", 0x02E137E8, 8),
)


def live_validation_plan() -> dict:
    modules = {
        "main": ((SOURCE / "XT30II_FW204_section_00260060.bin").read_bytes(), 0x01021000),
        "backend": ((SOURCE / MODELS["XT30II_FW204"]["file"]).read_bytes(), 0x01E12000),
    }
    windows = []
    for name, module, address, size in LIVE_FINGERPRINTS:
        blob, base = modules[module]
        raw = read_at(blob, base, address, size)
        windows.append({"name": name, "module": module, "address": hex(address),
                        "size": size, "reference_sha256": hashlib.sha256(raw).hexdigest()})
    return {
        "status": "prepared_not_captured", "fingerprints": windows,
        "data_after_fingerprints_match": [
            {"name": name, "address": hex(address), "size": size}
            for name, address, size in LIVE_FIXED_DATA
        ],
        "follow_pointers": False,
        "requirements": [
            "Fresh explicit cold Jig baseline; old RAM arena is invalid after power-off.",
            "Compare exact native code/data windows before trusting 2.04-derived globals.",
            "Capture selected profile and cached inputs at 29.97p and 59.94p in the same boot.",
            "Stop on any uncertain transport result; no automatic retry or cleanup command.",
            "No buffer, sensor, clock, bitrate, Flash, or persistent configuration changes.",
        ],
    }


def read_at(data: bytes, base: int, address: int, size: int) -> bytes:
    offset = address - base
    if size <= 0 or not 0 <= offset < offset + size <= len(data):
        raise ValueError(f"Reference read outside decoded module: {address:08x}/{size}")
    return data[offset:offset + size]


def audit_model(spec: dict) -> dict:
    data = (SOURCE / spec["file"]).read_bytes()
    base = spec["base"]
    if struct.unpack_from("<I", data, 4)[0] != base:
        raise ValueError("Decoded module base disagrees with its header")
    rows = []
    for pattern, profile in enumerate(spec["profiles"], 1):
        pools = {}
        for name, pool in spec["pools"].items():
            entry = spec["table"] + (profile * spec["row_width"] + pool) * 8
            count, reserved, pointer = struct.unpack("<hhI", read_at(data, base, entry, 8))
            if not 0 < count <= 64 or reserved != 0:
                raise ValueError("Unexpected resource count or descriptor header")
            raw = read_at(data, base, pointer, count * 28)
            descriptors = list(struct.iter_unpack("<7I", raw))
            pools[name] = {
                "pool_id": pool, "entry_address": hex(entry),
                "descriptor_address": hex(pointer), "count": count,
                "unique_descriptors": len(set(descriptors)),
                "unique_word0_word1_pairs": len({d[:2] for d in descriptors}),
                "descriptor_sha256": hashlib.sha256(raw).hexdigest(),
                "words": [[hex(w) for w in d] for d in descriptors],
            }
        rows.append({"pattern": pattern, "profile": profile, "pools": pools})
    return {
        "source": str(SOURCE / spec["file"]),
        "sha256": hashlib.sha256(data).hexdigest(),
        "table_address": hex(spec["table"]), "row_width": spec["row_width"],
        "allocator_address": hex(spec["allocator"]),
        "set_mode_address": hex(spec["set_mode"]), "rows": rows,
    }


def emulate_xt30_classifier() -> list[dict]:
    """Execute the actual ARM route classifier for 75 representative inputs.

    Native FPS enum 4/5/6 means 29.97/50/59.94 in the frame header consumer.
    Remaining inputs retain raw argument names until independently identified.
    """
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
    from unicorn.arm_const import (
        UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        UC_ARM_REG_SP, UC_ARM_REG_LR, UC_ARM_REG_PC,
    )
    uc = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    for filename, base in (("XT30II_FW204_section_00260060.bin", 0x01021000),
                           ("XT30II_FW204_section_00600060.bin", 0x01E12000)):
        blob = (SOURCE / filename).read_bytes()
        uc.mem_map(base, (len(blob) + 4095) & ~4095)
        uc.mem_write(base, blob)
    stack, result, sentinel = 0x0900F000, 0x09008000, 0x09001000
    uc.mem_map(0x09000000, 0x10000)
    rows = []
    for fps in (4, 5, 6):
        for arg3 in range(5):
            for arg4 in range(5):
                for reg, value in ((UC_ARM_REG_R0, 7), (UC_ARM_REG_R1, fps),
                                   (UC_ARM_REG_R2, arg3), (UC_ARM_REG_R3, arg4),
                                   (UC_ARM_REG_SP, stack), (UC_ARM_REG_LR, sentinel)):
                    uc.reg_write(reg, value)
                uc.mem_write(stack, struct.pack("<I", result))
                uc.mem_write(result, b"\xff")
                uc.emu_start(0x02219D70, sentinel, count=1000)
                selected = bytes(uc.mem_read(result, 1))[0]
                if uc.reg_read(UC_ARM_REG_PC) != sentinel or selected not in (4, 5, 6, 7):
                    raise ValueError(f"Classifier did not complete: {selected}")
                rows.append({"input_type": 7, "native_fps": fps, "arg3": arg3,
                             "arg4": arg4, "selected_type_and_profile": selected})
    return rows


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    models = {"XT30II_FW204": audit_model(MODELS["XT30II_FW204"])}
    rows = emulate_xt30_classifier()
    report = {
        "status": "offline_reference_audited", "camera_commands": 0,
        "models": models, "xt30_original_arm_classifier": rows,
        "live_validation_plan": live_validation_plan(),
        "limitations": [
            "The camera runs 2.06; these new 2.04 windows need a live fingerprint.",
            "Actual 60p cached inputs, selected profile, and allocated descriptors are not captured yet.",
            "Aliased entries support an overwrite hypothesis, not a proved cause or a safe patch.",
            "X-T3 addresses and buffer counts must not be copied to X-T30 II.",
        ],
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    for name, model in models.items():
        print(name)
        for row in model["rows"]:
            print(" pattern", row["pattern"], "profile", row["profile"],
                  {k: f"{v['unique_descriptors']}/{v['count']} distinct"
                   for k, v in row["pools"].items()})
    print("Original ARM classifier cases:", len(rows))
    for fps in (4, 5, 6):
        print(" native FPS", fps, "profiles", sorted({r["selected_type_and_profile"]
                                                     for r in rows if r["native_fps"] == fps}))


if __name__ == "__main__":
    main()
