"""Guarded route-4 resource-profile experiment in the retained REC arena.

Default is offline validation. Uses the established staging transport without
invoking its FPS operations. Target instruction is written only by native code.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

from normal_fps_patch import (PatchProtocol, STATE, CODE, RAW, ENTRY, REPORT, CLONE,
    ROOT_PTR, TABLE, CALLBACK, NORMAL_CALLBACK, LOADER, HEAP_L2, RULE_L2, ACTIONS, word)
from try_loader_probe import ApplicationError, PROJECT, OUT, SOURCE
from verify_loader_probe import capture
from capture_movie_buffer_state import preflight as capture_preflight

TARGET, ORIGINAL, REPLACEMENT = 0x02219ED0, 0xE3A00004, 0xE3A00006
REGION, REGION_SIZE, L1_TARGET, RX = 0x02200000, 0x100000, 0x0011C088, 0x0221EC06
MAGIC = 0x52535031


def build_page(snapshot, table, action):
    if len(snapshot) != 4096 or len(table) != 396 or action not in ACTIONS:
        raise ValueError("Invalid owned-page input")
    clone = bytearray(table)
    if struct.unpack_from("<3I", clone, 7 * 36) != (6, 0x01E12000, 0x8D9000):
        raise ValueError("Unexpected loader module")
    struct.pack_into("<II", clone, 7 * 36 + 4, STATE, 4096)
    code = (OUT / "normal_resource_patch.bin").read_bytes()
    if not 0 < len(code) <= 0xC00:
        raise ValueError("Payload exceeds retained page")
    page = bytearray(snapshot)
    struct.pack_into("<I", page, 12, ENTRY)
    struct.pack_into("<11I", page, 0x100, MAGIC, ACTIONS[action], *([0] * 9))
    page[0x200:0x200 + len(clone)] = clone
    page[0x400:0x400 + len(code)] = code
    return bytes(page)


def preflight(installation, fingerprints, action):
    arena = capture_preflight(installation, fingerprints)
    if (arena["allocation"], arena["code"], arena["state"]) != (RAW, CODE, STATE):
        raise ValueError("Payload is linked only for the verified allocation")
    digest = hashlib.sha256((OUT / "normal_resource_patch.bin").read_bytes()).hexdigest()
    report = json.loads((OUT / "normal_resource_emulation.json").read_text())
    if report["status"] != "passed" or report["payload_sha256"] != digest:
        raise ValueError("Exact payload lacks original ARM/kernel validation")
    if action == "apply":
        probe = json.loads((OUT / "normal_resource_probe_passed.json").read_text())
        if (probe["installation"] != str(installation.resolve())
                or probe["payload_sha256"] != digest or probe["status"] != "probe_verified_and_restored"):
            raise ValueError("This installation must first pass a write-free resource probe")
    return arena, digest


def run_patch(p, arena, action, folder, record):
    staged = armed = invoked = verified = False
    snapshot = None
    try:
        if p.debug() != 1:
            raise RuntimeError("Retained debug must already be enabled")
        if p.read(0x01780590, 12) != struct.pack("<3I", 1, NORMAL_CALLBACK, 0x02242B94):
            raise RuntimeError("Normal debug callbacks differ")
        if p.read(0x01B7B518, 1) != b"\3" or p.read(0x02CDDEB4, 2) != b"\3\0":
            raise RuntimeError("Not normal REC UI/root")
        if p.read(0x01722B84, 1) != b"\1":
            raise RuntimeError("SMP rendezvous is not ready")
        if p.read(0x02CDDE60, 2) != b"\2\7" or p.read(0x02E94A30, 1) != b"\7":
            raise RuntimeError("Must be idle with the original 30p resource profile")
        roots = struct.unpack("<2I", p.read(0x02E137E8, 8))
        if any(v not in (0, 0xFFFFFFFF) for v in roots):
            raise RuntimeError("Recording context remains active")
        settings = p.read(0x0177F8C0, 164)
        if any(settings[o] != v for o, v in ((0x2B, 0), (0x2D, 3), (0x74, 1),
                                            (0x75, 0), (0x90, 1), (0xA1, 1))):
            raise RuntimeError("Require UHD 29.97 MOV/H264 LongGOP 200 before changing policy")
        if p.read(0x01B85AD2, 1) != b"\4" or p.read(0x013E1788, 4) != word(0x7FFFFFFE):
            raise RuntimeError("Unexpected cached FPS or FPS policy")
        if p.read(ROOT_PTR, 8) != struct.pack("<2I", TABLE, 0x00E201EC):
            raise RuntimeError("Loader roots changed")
        table = p.read(TABLE, 396)
        if table != capture(TABLE, 396):
            raise RuntimeError("Loader descriptor table changed")
        if (p.read(L1_TARGET, 4) != word(RX) or p.read(0x0011C070, 4) != word(HEAP_L2 | 1)
                or p.read(0x0011C04C, 4) != word(RULE_L2 | 1)):
            raise RuntimeError("Section or owned-page mapping differs")
        heap = p.read(HEAP_L2, 1024)
        rules = p.read(RULE_L2, 1024)
        if (struct.unpack_from("<I", heap, 0x74)[0] != CODE | 0x7B6
                or struct.unpack_from("<I", heap, 0x78)[0] != STATE | 0x5B7):
            raise RuntimeError("Owned code/data permissions differ")
        code = p.read(CODE, 836)
        if hashlib.sha256(code).hexdigest() != arena["code_sha256"]:
            raise RuntimeError("Resident code identity differs")
        snapshot = p.read(STATE, 4096)
        state = struct.unpack_from("<24I", snapshot)
        if state[:7] != (0x52454348, 2, RAW, CODE, STATE, 0, 3) or state[13] or state[15]:
            raise RuntimeError("Resident lifecycle is not completed and inactive")
        before = p.read(REGION, REGION_SIZE)
        expected = REPLACEMENT if action == "restore" else ORIGINAL
        replacement = REPLACEMENT if action == "apply" else ORIGINAL
        reference = (SOURCE / "XT30II_FW204_section_00600060.bin").read_bytes()
        function = bytearray(reference[0x02219E44 - 0x01E12000:0x02219EDC - 0x01E12000])
        struct.pack_into("<I", function, TARGET - 0x02219E44, expected)
        if before[0x19E44:0x19EDC] != function:
            raise RuntimeError("Complete native resource mapper differs")
        if before[0x40D84:0x40D88] != word(arena["usb_branch"]):
            raise RuntimeError("Retained USB attach branch differs")
        protect_lists = p.read(0x025D1CA8, 0x1C0)
        if protect_lists != reference[0x025D1CA8 - 0x01E12000:0x025D1E68 - 0x01E12000]:
            raise RuntimeError("Native profile protection tables differ")
        for name, data in (("owned_page_original.bin", snapshot), ("heap_l2_original.bin", heap),
                           ("rule_l2_original.bin", rules), ("code_region_original.bin", before),
                           ("profile_protection_lists.bin", protect_lists), ("settings_before.bin", settings)):
            (folder / name).write_bytes(data)
        page = build_page(snapshot, table, action)
        (folder / "staged_page.bin").write_bytes(page)
        record("live_guards_passed", action=action, expected=hex(expected), replacement=hex(replacement),
               recording=False, selected_fps="29.97", profile=7, policy_write_planned=action != "probe")
        staged = True
        p.write(STATE + 0x100, page[0x100:])
        if p.read(STATE + 0x100, 0xF00) != page[0x100:]:
            raise RuntimeError("Staging readback mismatch")
        armed = True
        for address, value in ((STATE + 12, ENTRY), (ROOT_PTR, CLONE), (CALLBACK, LOADER)):
            p.write(address, word(value))
            if p.read(address, 4) != word(value):
                raise RuntimeError("Arming readback mismatch")
        command = b"CMD X\n"
        record("invoke_once", action=action)
        invoked = True
        try:
            p.transaction(0x200001, 5, struct.pack("<4I", 0, 0, 0, len(command)), payload=command)
        except ApplicationError:
            invoked = False
            raise
        result = struct.unpack("<11I", p.read(REPORT, 44))
        record("native_report", words=list(map(hex, result)))
        if result[:3] != (MAGIC, ACTIONS[action], 2):
            raise RuntimeError("Native operation did not complete")
        for address, value in ((STATE + 12, CODE), (ROOT_PTR, TABLE), (CALLBACK, NORMAL_CALLBACK),
                               (L1_TARGET, RX), (0x013E1788, 0x7FFFFFFE)):
            if p.read(address, 4) != word(value):
                raise RuntimeError("Native restoration or unchanged FPS policy failed")
        if p.read(HEAP_L2, 1024) != heap or p.read(RULE_L2, 1024) != rules:
            raise RuntimeError("Exact page-table restoration failed")
        after = p.read(REGION, REGION_SIZE)
        (folder / "code_region_after.bin").write_bytes(after)
        expected_region = bytearray(before)
        struct.pack_into("<I", expected_region, TARGET - REGION, replacement)
        if after != expected_region:
            raise RuntimeError("Unexpected difference in complete 1 MiB code section")
        state_after = p.read(STATE, 96)
        if state_after[:64] != snapshot[:64] or state_after[80:] != snapshot[80:96]:
            raise RuntimeError("Resident lifecycle changed unexpectedly")
        if p.read(CODE, 836) != code or p.debug() != 1:
            raise RuntimeError("Resident code or debug flag changed")
        if p.read(0x0177F8C0, 164) != settings or p.read(0x02CDDE60, 2) != b"\2\7":
            raise RuntimeError("Settings or recording state changed during operation")
        verified = True
        record("operation_verified", target=hex(TARGET), value=hex(replacement),
               region_bytes_checked=REGION_SIZE, exact_page_tables_restored=True,
               resident_code_and_fps_policy_unchanged=True)
    finally:
        if not p.healthy:
            record("transport_uncertain", additional_commands=0)
        elif not invoked:
            if armed:
                for address, value in ((CALLBACK, NORMAL_CALLBACK), (ROOT_PTR, TABLE), (STATE + 12, CODE)):
                    p.write(address, word(value))
                    if p.read(address, 4) != word(value):
                        raise RuntimeError("Predispatch restoration failed")
            if staged:
                p.write(STATE + 0x100, snapshot[0x100:])
                if p.read(STATE + 0x100, 0xF00) != snapshot[0x100:]:
                    raise RuntimeError("Staging restoration failed")
            record("predispatch_controls_restored")
        elif verified:
            p.write(STATE + 0x100, snapshot[0x100:])
            if p.read(STATE + 0x100, 0xF00) != snapshot[0x100:]:
                raise RuntimeError("Staging restoration failed")
            record("owned_staging_restored", bytes=0xF00, readback_verified=True)
        else:
            record("native_result_unverified", no_cleanup_writes=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("installation", type=Path)
    parser.add_argument("fingerprints", type=Path)
    parser.add_argument("--action", choices=ACTIONS, default="probe")
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    arena, digest = preflight(args.installation, args.fingerprints, args.action)
    if not args.execute:
        print(json.dumps({"preflight": "passed", "action": args.action,
                          "target": hex(TARGET), "payload_sha256": digest, "persistent_writes": False}))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = OUT / f"normal_resource_{args.action}_{stamp}"
    folder.mkdir()
    log = {"utc": stamp, "installation": str(args.installation.resolve()), "action": args.action,
           "payload_sha256": digest, "events": [], "status": "running", "persistent_writes": False}
    def record(event, **fields):
        log["events"].append({"event": event, **fields})
        (folder / "journal.json").write_text(json.dumps(log, indent=2) + "\n")
        print(event, json.dumps(fields), flush=True)
    sys.path.insert(0, str(PROJECT / "vendor/fffw/ff80"))
    import usb1, fftlib
    handle = None
    try:
        with usb1.USBContext() as ctx:
            devices = [d for d in ctx.getDeviceList(skip_on_error=False)
                       if (d.getVendorID(), d.getProductID()) == (0x04CB, 0xFF80)]
            if len(devices) != 1:
                raise RuntimeError("Need exactly one retained-debug camera")
            handle = devices[0].open()
            with handle.claimInterface(0):
                transport = fftlib.ftl(handle)
                transport.ms = 5000
                transport.open_session()
                if len(transport.ping()) != 2:
                    raise RuntimeError("Invalid handshake")
                p = PatchProtocol(transport, record)
                try:
                    run_patch(p, arena, args.action, folder, record)
                    log["status"] = args.action + "_verified_and_restored"
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
    if log["status"] == "probe_verified_and_restored":
        (OUT / "normal_resource_probe_passed.json").write_text(json.dumps(log, indent=2) + "\n")
    return 0 if log["status"].endswith("_verified_and_restored") else 1


if __name__ == "__main__":
    raise SystemExit(main())
