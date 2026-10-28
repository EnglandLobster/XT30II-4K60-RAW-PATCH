"""Read fixed movie-state windows in a verified, retained REC debug session.

Default is offline validation. No RAM/configuration writes, retries, recording
commands, or pointer following. The capture is sequential, not an atomic dump.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from audit_movie_buffer_profiles import LIVE_FIXED_DATA, live_validation_plan
from try_loader_probe import GuardedProtocol, PROJECT, OUT, SOURCE

WINDOWS = (
    ("autoset", 0x0177F8C0, 164),
    ("rec_parameters", 0x01AE7E88, 1492),
    *LIVE_FIXED_DATA,
)
CONTROLS = ((0x01780590, 12), (0x01B7B518, 1), (0x02CDDEB4, 2))
# Native 0221c8dc stores index, selected pool, route/mode/format and FPS into
# slot 0 at these exact addresses. Do not derive an arbitrary read from RAM.
ACTIVE_SLOT0 = 0x02E137F0
ACTIVE_SLOT0_WINDOWS = (
    ("active_slot_index", ACTIVE_SLOT0 + 4, 4),
    ("active_encode_pool", ACTIVE_SLOT0 + 0x660, 1),
    ("active_route_mode_formats", ACTIVE_SLOT0 + 0xA8C, 6),
    ("active_native_fps", ACTIVE_SLOT0 + 0xAEA, 1),
)


class ReadOnlyProtocol(GuardedProtocol):
    def __init__(self, transport, record, arena, active_slot0=False):
        super().__init__(transport, record)
        self.ranges = [(a, a + n) for _, a, n in WINDOWS]
        self.ranges += [(a, a + n) for a, n in CONTROLS]
        self.ranges += [(arena["state"], arena["state"] + 96),
                        (arena["code"], arena["code"] + 836)]
        if active_slot0:
            self.ranges += [(a, a + n) for _, a, n in ACTIVE_SLOT0_WINDOWS]

    def transaction(self, op, fn, params, length=0, payload=b""):
        debug_read = (op, fn, params, length) == (
            0x1A0002, 2, struct.pack("<4I", 1, 0, 0xF7, 1), 1)
        ram_read = False
        if op == 0x200001 and fn == 2 and len(params) == 16:
            z0, z1, address, count = struct.unpack("<4I", params)
            ram_read = (z0 == z1 == 0 and count == length and 0 < count <= 256
                        and any(lo <= address < address + count <= hi for lo, hi in self.ranges))
        if payload or not (debug_read or ram_read):
            raise ValueError("Only whitelisted fixed-window reads are permitted")
        return super().transaction(op, fn, params, length, payload)


def preflight(installation: Path, fingerprints: Path) -> dict:
    arena = json.loads((installation / "owned_arena.json").read_text())
    acceptance = json.loads((OUT / "rec_v2_acceptance.json").read_text())
    if (arena.get("state_version") != 2 or acceptance["installation"] != installation.name
            or acceptance["status"] != "normal_view_and_retained_ram_debug_verified"
            or acceptance["code_sha256"] != arena["code_sha256"]):
        raise ValueError("Current installation lacks confirmed normal REC acceptance")
    verified = json.loads(fingerprints.read_text())
    expected = live_validation_plan()["fingerprints"]
    if verified["status"] != "passed" or len(verified["checks"]) != len(expected):
        raise ValueError("Complete live code/table fingerprints are required")
    for entry, reference in zip(verified["checks"], expected):
        data = (SOURCE / entry["file"]).read_bytes()
        if (entry["address"] != reference["address"] or len(data) != reference["size"]
                or hashlib.sha256(data).hexdigest() != reference["reference_sha256"]):
            raise ValueError("Code/table fingerprint is stale or mismatched")
    return arena


def collect(p, arena, folder, record, active_slot0=False):
    if p.debug() != 1:
        raise RuntimeError("Retained debug must already be enabled; no flag writes")
    state = struct.unpack("<24I", p.read(arena["state"], 96))
    if (state[:7] != (0x52454348, 2, arena["allocation"], arena["code"], arena["state"], 0, 3)
            or state[13] != 0 or state[15] != 0):
        raise RuntimeError("Retained installation identity or lifecycle differs")
    if hashlib.sha256(p.read(arena["code"], 836)).hexdigest() != arena["code_sha256"]:
        raise RuntimeError("Resident code differs")
    for (address, size), expected in zip(CONTROLS, (
            struct.pack("<3I", 1, 0x020A0B54, 0x02242B94), b"\x03", b"\x03\0")):
        if p.read(address, size) != expected:
            raise RuntimeError(f"Not expected normal REC control state: {address:08x}")
    data = {}
    for name, address, size in WINDOWS:
        record("read_window", name=name, address=hex(address), bytes=size)
        data[name] = p.read(address, size)
        (folder / f"{name}.bin").write_bytes(data[name])
        record("window_saved", name=name, sha256=hashlib.sha256(data[name]).hexdigest())
    active = None
    if active_slot0:
        if struct.unpack("<2I", data["active_context_roots"])[1] != ACTIVE_SLOT0:
            raise RuntimeError("Expected active slot 0 is absent; no object memory read")
        for name, address, size in ACTIVE_SLOT0_WINDOWS:
            data[name] = p.read(address, size)
            (folder / f"{name}.bin").write_bytes(data[name])
        if data["active_slot_index"] != bytes(4):
            raise RuntimeError("Active object is not slot 0")
        active = {
            "address": hex(ACTIVE_SLOT0), "index": 0,
            "encode_pool": data["active_encode_pool"][0],
            "route_mode_formats": list(data["active_route_mode_formats"]),
            "native_fps": data["active_native_fps"][0],
        }
    stable = {}
    for name, address, size in WINDOWS:
        if name not in ("autoset", "resource_state_type_flags", "selected_resource_profile", "active_context_roots"):
            continue
        after = p.read(address, size)
        (folder / f"{name}_after.bin").write_bytes(after)
        stable[name] = after == data[name]
    if p.read(0x01B7B518, 1) != b"\x03" or p.read(0x02CDDEB4, 2) != b"\x03\0":
        raise RuntimeError("UI changed during capture")
    route = data["route_parameter_cache"]
    frame = data["frame_parameter_cache"]
    auto = data["autoset"]
    result = {
        "selected_profile": data["selected_resource_profile"][0],
        "resource_state_type_flags": list(data["resource_state_type_flags"]),
        "route_classifier_inputs": [route[0x15], route[0x1E], route[0x3FC], route[0x40E]],
        "frame_pool_inputs": [frame[0x3FC], frame[0x40E]],
        "active_context_roots": [hex(x) for x in struct.unpack("<2I", data["active_context_roots"])],
        "autoset": {name: auto[offset] for name, offset in {
            "pixel": 0x2B, "fps": 0x2D, "bitrate": 0x74, "compression": 0x75,
            "codec": 0x90, "flog_hlg": 0x91, "file_format_codec": 0xA1}.items()},
        "boundary_stability": stable,
        "atomic": False,
        "active_slot0": active,
    }
    (folder / "decoded.json").write_text(json.dumps(result, indent=2) + "\n")
    if not all(stable.values()):
        raise RuntimeError("Mode/settings changed; keep evidence, do not treat as stable snapshot")
    record("snapshot_verified", **result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installation", type=Path)
    parser.add_argument("fingerprints", type=Path)
    parser.add_argument("--label", required=True)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--active-slot0", action="store_true",
                        help="Read four fixed fields only if the active object is verified slot 0")
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_]{1,48}", args.label):
        parser.error("Use a short lowercase label")
    arena = preflight(args.installation, args.fingerprints)
    if not args.execute:
        print(json.dumps({"preflight": "passed", "windows": WINDOWS, "writes": False,
                          "conditional_active_slot0_fields": ACTIVE_SLOT0_WINDOWS if args.active_slot0 else []}))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = OUT / f"movie_buffers_{args.label}_{stamp}"
    folder.mkdir()
    log = {"utc": stamp, "label": args.label, "installation": str(args.installation.resolve()),
           "fingerprints": str(args.fingerprints.resolve()), "status": "running", "events": []}
    def record(event, **fields):
        log["events"].append({"utc": datetime.now(timezone.utc).isoformat(), "event": event, **fields})
        (folder / "journal.json").write_text(json.dumps(log, indent=2) + "\n")
        print(event, json.dumps(fields), flush=True)
    sys.path.insert(0, str(PROJECT / "vendor/fffw/ff80"))
    import usb1, fftlib
    handle = None
    try:
        with usb1.USBContext() as ctx:
            devices = [d for d in ctx.getDeviceList(skip_on_error=True)
                       if (d.getVendorID(), d.getProductID()) == (0x04CB, 0xFF80)]
            if len(devices) != 1:
                raise RuntimeError("Require exactly one retained ff80 camera")
            handle = devices[0].open()
            with handle.claimInterface(0):
                transport = fftlib.ftl(handle)
                transport.ms = 5000
                transport.open_session()
                if len(transport.ping()) != 2:
                    raise RuntimeError("Invalid session handshake")
                p = ReadOnlyProtocol(transport, record, arena, args.active_slot0)
                try:
                    collect(p, arena, folder, record, args.active_slot0)
                    log["status"] = "stable_fixed_windows_captured"
                finally:
                    if p.healthy:
                        transport.close_session()
                        record("session_closed")
    except Exception as error:
        log["status"] = "stopped_on_error"
        record("error", type=type(error).__name__, message=str(error))
    finally:
        if handle is not None:
            handle.close()
        record("finished", status=log["status"])
        print("RESULT", folder)
    return 0 if log["status"] == "stable_fixed_windows_captured" else 1


if __name__ == "__main__":
    raise SystemExit(main())
