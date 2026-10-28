"""One guarded, reversible RAM callback experiment; never a firmware/FPS patch.

Default is an offline preflight. --execute temporarily connects the existing
original key parser to its empty callback slot, sends MODE REC once, restores
the slot and volatile debug flag, and closes the same ff80 session. Valid
application rejections permit cleanup; an incomplete/invalid transport response
stops all further commands and leaves a precise recovery journal.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "src/offline_20261011"
CALLBACK = 0x01780598
PARSER = 0x02242B94
SINK = 0x0129D1D0


def preflight():
    checks = []
    for address, size, base, section in (
        (0x011898C4, 0x130, 0x01021000, "00260060"),
        (SINK, 0x118, 0x01021000, "00260060"),
        (0x0209AA94, 0x2E8, 0x01E12000, "00600060"),
        (PARSER, 0x13C, 0x01E12000, "00600060"),
        (0x0129C708, 0xA4, 0x01021000, "00260060"),
    ):
        files = sorted(OUT.glob(f"window_{address:08x}_*.bin"))
        if not files:
            raise ValueError(f"No live evidence for {address:#x}")
        actual = files[-1].read_bytes()
        reference = (OUT / f"XT30II_FW204_section_{section}.bin").read_bytes()
        expected = reference[address-base:address-base+size]
        if len(actual) != size or actual != expected:
            raise ValueError(f"Code fingerprint mismatch at {address:#x}")
        metadata = json.loads(files[-1].with_suffix(".json").read_text())
        if metadata["status"] != "success":
            raise ValueError("Live evidence acquisition did not finish cleanly")
        checks.append({"address": hex(address), "bytes": size,
                       "evidence": files[-1].name, "sha256": hashlib.sha256(actual).hexdigest()})
    return checks


class ApplicationError(Exception):
    pass


def main():
    argp = argparse.ArgumentParser(description=__doc__)
    argp.add_argument("--execute", action="store_true")
    args = argp.parse_args()
    checks = preflight()
    if not args.execute:
        print(json.dumps({"preflight": "pass", "code_checks": checks,
            "ram_slot": hex(CALLBACK), "temporary_value": hex(PARSER),
            "command": "MODE REC\\n", "fps_or_flash_writes": False}, indent=2))
        return 0

    sys.path.insert(0, str(ROOT / "vendor/fffw/ff80"))
    import usb1
    import fftlib
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = OUT / f"native_rec_callback_{stamp}.json"
    log = {"utc": stamp, "code_checks": checks, "events": [],
           "fps_or_flash_writes": False, "status": "running"}
    ready = False
    opened = False
    old_debug = None
    callback_may_be_changed = False
    debug_may_be_changed = False
    handle = None

    def record(name, **fields):
        log["events"].append({"event": name, **fields})
        path.write_text(json.dumps(log, indent=2) + "\n")
        print(name, json.dumps(fields), flush=True)

    try:
        with usb1.USBContext() as context:
            devices = [d for d in context.getDeviceList(skip_on_error=True)
                       if (d.getVendorID(), d.getProductID()) == (0x04CB, 0xFF80)]
            if len(devices) != 1:
                raise RuntimeError("Require exactly one Jig device")
            handle = devices[0].open()
            with handle.claimInterface(0):
                transport = fftlib.ftl(handle)
                transport.ms = 3000
                transport.open_session()
                opened = True
                ready = True
                if len(transport.ping()) != 2:
                    ready = False
                    raise RuntimeError("Invalid ping")
                record("session_ready", packet=transport.max_pkt_size)

                def transact(op, fn, params, length=0, payload=b""):
                    nonlocal ready
                    ready = False
                    transport.write_cmd(struct.pack("<5I", op, 0, 0, 0, fn) + params + payload)
                    response = bytes(transport.read_cmd(36 + length))
                    if len(response) < 36:
                        raise RuntimeError("Short response; transport state unknown")
                    h = struct.unpack_from("<5I", response)
                    if (h[0], h[3], h[4]) != (op, 0, fn):
                        raise RuntimeError("Unexpected response header; transport state unknown")
                    if h[1] or h[2]:
                        if len(response) != 36:
                            raise RuntimeError("Unexpected application error response length")
                        # Complete synchronous rejection, no pending data phase.
                        ready = True
                        record("application_rejection", opcode=hex(op), function=fn,
                               status=list(h[1:3]), response=response.hex())
                        raise ApplicationError(str(h[1:3]))
                    if len(response) != 36 + length or response[20:36] != params:
                        raise RuntimeError("Response length/echo mismatch; transport state unknown")
                    ready = True
                    return response[36:]

                cfg = struct.pack("<4I", 1, 0, 0xF7, 1)

                def read(address, size):
                    if size > min(256, transport.max_pkt_size):
                        raise ValueError("Read exceeds one bounded packet")
                    return transact(0x200001, 2, struct.pack("<4I", 0, 0, address, size), size)

                def write_callback(value):
                    if value not in (0, PARSER):
                        raise ValueError("Only the original zero and known native parser are allowed")
                    transact(0x200001, 3, struct.pack("<4I", 0, 0, CALLBACK, 4),
                             payload=struct.pack("<I", value))

                try:
                    old_debug = transact(0x1A0002, 2, cfg, 1)[0]
                    record("debug_original", value=old_debug)
                    if old_debug != 0:
                        raise RuntimeError("Unexpected pre-existing debug configuration")
                    debug_may_be_changed = True
                    transact(0x1A0002, 3, cfg, payload=b"\x01")
                    if transact(0x1A0002, 2, cfg, 1) != b"\x01":
                        raise RuntimeError("Debug enable readback failed")
                    state = struct.unpack("<3I", read(0x01780590, 12))
                    sink = struct.unpack("<I", read(0x01722BB0, 4))[0]
                    mode = read(0x01B6A020, 1)[0]
                    record("runtime_guard", debug_state=list(state), event_sink=hex(sink), mode=mode)
                    if state != (0, 0, 0) or sink != SINK:
                        raise RuntimeError("Runtime state differs from the prepared experiment")
                    callback_may_be_changed = True
                    write_callback(PARSER)
                    if read(CALLBACK, 4) != struct.pack("<I", PARSER):
                        raise RuntimeError("Callback write readback failed")
                    record("callback_connected", address=hex(CALLBACK), value=hex(PARSER))
                    payload = b"MODE REC\n"
                    record("mode_request", payload=payload.decode(), attempts=1)
                    transact(0x200001, 5, struct.pack("<4I", 0, 0, 0, len(payload)), payload=payload)
                    record("mode_request_acknowledged", status=[0, 0])
                    log["status"] = "command_acknowledged"
                finally:
                    if ready:
                        if callback_may_be_changed:
                            write_callback(0)
                            if read(CALLBACK, 4) != bytes(4):
                                raise RuntimeError("Callback restoration readback failed")
                            callback_may_be_changed = False
                            record("callback_restored", value=0)
                        if debug_may_be_changed:
                            transact(0x1A0002, 3, cfg, payload=bytes([old_debug]))
                            if transact(0x1A0002, 2, cfg, 1) != bytes([old_debug]):
                                raise RuntimeError("Debug restoration readback failed")
                            debug_may_be_changed = False
                            record("debug_restored", value=old_debug)
                        if opened:
                            ready = False
                            transport.close_session()
                            opened = False
                            ready = True
                            record("session_closed")
                    else:
                        record("transport_uncertain_no_cleanup_commands")
    except Exception as exc:
        log["status"] = "stopped_on_error"
        record("error", type=type(exc).__name__, message=str(exc))
    finally:
        if handle is not None:
            handle.close()
        log["callback_restore_unconfirmed"] = callback_may_be_changed
        log["debug_restore_unconfirmed"] = debug_may_be_changed
        record("finished", status=log["status"], callback_restore_unconfirmed=callback_may_be_changed,
               debug_restore_unconfirmed=debug_may_be_changed)
        print("RESULT", path)
    return 0 if log["status"] == "command_acknowledged" else 1


if __name__ == "__main__":
    raise SystemExit(main())
