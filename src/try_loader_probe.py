"""Guarded RAM-only native-loader experiments. Default: offline preflight.

No FPS, sensor, mode, Flash or persistent configuration writes. rec_install_probe
installs a disabled UI callback and retains owned memory until a cold restart.
Host writes are
restricted to one inactive log page, the descriptor-root pointer, CMD callback,
and volatile f7. The probe calls the original protection API; no host page-table
writes. An uncertain transport response forbids all further camera commands.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

from verify_loader_probe import (SOURCE, OUT, SCRATCH, TABLE, ROOT_PTR, CALLBACK,
                                 CLONE, LOADER, L1, L2, PTE, capture, build_page,
                                 INSTALL_PROBES, PROBES)

PROJECT = Path(__file__).resolve().parents[1]


class ApplicationError(RuntimeError):
    pass


class GuardedProtocol:
    def __init__(self, transport, record):
        self.transport, self.record = transport, record
        self.healthy = True

    def transaction(self, op, fn, params, length=0, payload=b""):
        if not self.healthy:
            raise RuntimeError("Transport uncertain; further commands forbidden")
        self.healthy = False
        self.transport.write_cmd(struct.pack("<5I", op, 0, 0, 0, fn) + params + payload)
        response = bytes(self.transport.read_cmd(36 + length))
        if len(response) < 36:
            raise RuntimeError("Short response")
        header = struct.unpack_from("<5I", response)
        if (header[0], header[3], header[4]) != (op, 0, fn):
            raise RuntimeError("Unexpected response identity")
        if header[1:3] != (0, 0):
            if len(response) != 36:
                raise RuntimeError("Unexpected rejection length")
            self.healthy = True
            self.record("application_rejection", opcode=hex(op), function=fn,
                        status=list(header[1:3]), response=response.hex())
            raise ApplicationError(str(header[1:3]))
        if len(response) != 36 + length or response[20:36] != params:
            raise RuntimeError("Response length or parameter echo mismatch")
        self.healthy = True
        return response[36:]

    def read(self, address, size):
        data = bytearray()
        while len(data) < size:
            n = min(256, size - len(data))
            data.extend(self.transaction(0x200001, 2,
                        struct.pack("<4I", 0, 0, address + len(data), n), n))
        return bytes(data)

    def write(self, address, data):
        allowed = SCRATCH <= address < address + len(data) <= SCRATCH + 0x1000
        if address == ROOT_PTR:
            allowed = data in (struct.pack("<I", TABLE), struct.pack("<I", CLONE))
        if address == CALLBACK:
            allowed = data in (bytes(4), struct.pack("<I", LOADER))
        if not allowed:
            raise ValueError("Write outside this probe's ownership")
        for offset in range(0, len(data), 256):
            chunk = data[offset:offset + 256]
            self.transaction(0x200001, 3,
                             struct.pack("<4I", 0, 0, address + offset, len(chunk)), payload=chunk)

    def debug(self, value=None):
        params = struct.pack("<4I", 1, 0, 0xF7, 1)
        if value is None:
            return self.transaction(0x1A0002, 2, params, 1)[0]
        if value not in (0, 1):
            raise ValueError("Unexpected debug flag value")
        self.transaction(0x1A0002, 3, params, payload=bytes([value]))
        if self.debug() != value:
            raise RuntimeError("Debug flag readback mismatch")


def preflight(payload_name="loader_probe"):
    report = json.loads((OUT / f"{payload_name}_emulation.json").read_text())
    if report["status"] != "passed":
        raise ValueError("Offline execution failed")
    table = capture(TABLE, 396)
    page = build_page(table, payload_name)
    if hashlib.sha256(page).hexdigest() != report["scratch_page_sha256"]:
        raise ValueError("Payload changed since offline verification")
    if page != (OUT / f"{payload_name}_page.bin").read_bytes():
        raise ValueError("Page differs from tested artifact")
    if capture(L2, 1024)[PTE-L2:PTE-L2+4] != struct.pack("<I", 0x06B955B7):
        raise ValueError("Target is not the expected existing 4 KiB page")
    if payload_name in INSTALL_PROBES:
        usb=json.loads((OUT/'rec_usb_emulation.json').read_text())
        lifecycle=json.loads((OUT/'rec_lifecycle_emulation.json').read_text())
        digest=hashlib.sha256((OUT/'rec_lifecycle_hook.bin').read_bytes()).hexdigest()
        if any(r['status']!='passed' or r['hook_sha256']!=digest for r in (usb,lifecycle)):
            raise ValueError('Lifecycle and USB guard must both pass with this exact artifact')
    if payload_name == 'rec_install_label_probe':
        from movie_bitrate_label import blob, font_reference
        font_reference()
        checks=json.loads((OUT/'movie_bitrate_label_emulation.json').read_text())
        if checks['status']!='passed' or checks['label_sha256']!=hashlib.sha256(blob()).hexdigest():
            raise ValueError('Exact label provider has not passed native resource tests')
    return table, page


def run_probe(protocol, folder, record, expected_table, page, payload_name="loader_probe"):
    debug_changed = scratch_changed = armed = executed = False
    snapshot, saved_l2 = None, None
    success = False
    try:
        if protocol.debug() != 0:
            raise RuntimeError("Debug flag was already enabled")
        debug_changed = True
        protocol.debug(1)
        if protocol.read(0x01780590, 12) != bytes(12):
            raise RuntimeError("Logging or callbacks already active")
        if protocol.read(0x01B6A020, 1) != b"\x07":
            raise RuntimeError("Not the known Jig backend mode")
        if payload_name in INSTALL_PROBES:
            if protocol.read(0x02240d84,4)!=struct.pack('<I',0x0affffe2):
                raise RuntimeError('Attach branch differs from stock')
            if protocol.read(L1+0x22*4,4)!=struct.pack('<I',0x0221ec06):
                raise RuntimeError('Attach code section differs from prepared RX mapping')
            if protocol.read(L1+0x1c*4,4)!=struct.pack('<I',0xa0401):
                raise RuntimeError('Private heap-page preparation missing')
        label_before=None
        if payload_name == 'rec_install_label_probe':
            from movie_bitrate_label import FONT_WINDOW, FONT_SIZE, font_reference, BANK_POINTER
            if protocol.read(0x01b7b518,1)!=b'\x0c' or protocol.read(0x01a4117c,1)!=b'\0':
                raise RuntimeError('Label prologues require cold Jig before REC activation')
            if protocol.read(L1+0x3e*4,4)!=struct.pack('<I',0x03e16c06):
                raise RuntimeError('Graphics map differs from this 2.06 build')
            if protocol.read(BANK_POINTER,4)!=struct.pack('<I',0x008a0000):
                raise RuntimeError('Active font bank differs')
            if protocol.read(FONT_WINDOW,FONT_SIZE)!=font_reference():
                raise RuntimeError('Exact complete font-accessor window differs')
            if any(protocol.read(a,10)!=struct.pack('<5H',0,0,30,36,48)
                   for a in (0x001e5438,0x001e5b7c)):
                raise RuntimeError('ISO/bitrate font metrics differ')
            label_before=protocol.read(0x03eb6000,4096)
            (folder/'graphics_page_original.bin').write_bytes(label_before)
        if protocol.read(0x01722B84, 1) != b"\x01":
            raise RuntimeError("Native SMP rendezvous not ready")
        if protocol.read(ROOT_PTR, 8) != struct.pack("<II", TABLE, 0x00E201EC):
            raise RuntimeError("Loader roots changed")
        if protocol.read(TABLE, 396) != expected_table:
            raise RuntimeError("Live loader table changed")
        if protocol.read(L1 + 0x6B * 4, 4) != struct.pack("<I", L2 | 1):
            raise RuntimeError("Log page mapping changed")
        saved_l2 = protocol.read(L2, 1024)
        if saved_l2 != capture(L2, 1024):
            raise RuntimeError("Log page permissions changed")
        snapshot = protocol.read(SCRATCH, 4096)
        (folder / "scratch_original.bin").write_bytes(snapshot)
        (folder / "l2_original.bin").write_bytes(saved_l2)
        (folder / "loader_table_original.bin").write_bytes(expected_table)
        record("guards_passed", scratch_original_sha256=hashlib.sha256(snapshot).hexdigest())
        scratch_changed = True
        protocol.write(SCRATCH, page)
        if protocol.read(SCRATCH, 4096) != page:
            raise RuntimeError("Staged page mismatch")
        record("page_staged_and_verified", sha256=hashlib.sha256(page).hexdigest())
        # Full clone preserves every descriptor except the temporary module-6
        # base/size; the original descriptor array is never changed.
        armed = True
        protocol.write(ROOT_PTR, struct.pack("<I", CLONE))
        protocol.write(CALLBACK, struct.pack("<I", LOADER))
        if protocol.read(ROOT_PTR, 4) != struct.pack("<I", CLONE):
            raise RuntimeError("Root arm readback failed")
        if protocol.read(CALLBACK, 4) != struct.pack("<I", LOADER):
            raise RuntimeError("Callback arm readback failed")
        payload = b"CMD X\n"
        record("invoke_once", operation="native loader -> marker probe -> native RW/XN restore")
        executed = True
        protocol.transaction(0x200001, 5, struct.pack("<4I", 0, 0, 0, len(payload)), payload=payload)
        record("native_call_returned", status=[0, 0])
        if protocol.read(ROOT_PTR, 4) != struct.pack("<I", TABLE):
            raise RuntimeError("Probe did not restore loader root")
        if protocol.read(CALLBACK, 4) != bytes(4):
            raise RuntimeError("Probe did not restore callback")
        marker = 0x52494e31 if payload_name in INSTALL_PROBES else 0x50525831 if payload_name=='private_exec_probe' else 0x50524F42
        if protocol.read(SCRATCH + 0x180, 4) != struct.pack("<I", marker):
            raise RuntimeError("Probe marker absent")
        if protocol.read(L2, 1024) != saved_l2:
            raise RuntimeError("Native permission restoration mismatch")
        if protocol.read(L1 + 0x6B * 4, 4) != struct.pack("<I", L2 | 1):
            raise RuntimeError("L1 mapping changed")
        if protocol.read(TABLE, 396) != expected_table:
            raise RuntimeError("Original descriptors changed")
        if protocol.read(0x01B6A020, 1) != b"\x07":
            raise RuntimeError("Unexpected backend mode change")
        armed = False
        record("probe_verified", marker=hex(marker), full_log_l2_restored=True,
               loader_root_restored=True, callback_restored=True, backend_mode=7)
        if payload_name == "allocator_probe":
            raw, aligned, freed = struct.unpack("<3I", protocol.read(SCRATCH + 0x184, 12))
            if not (raw != 0 and raw <= aligned and aligned + 4096 <= raw + 8192
                    and aligned & 4095 == 0 and freed == 0xFEEEFEEE):
                raise RuntimeError("Native allocation/free result invalid")
            record("native_allocation_freed", allocation=hex(raw), aligned_page=hex(aligned), bytes=8192)
        if payload_name == "private_exec_probe":
            fields = struct.unpack("<10I", protocol.read(SCRATCH + 0x180, 40))
            names = ("magic", "status", "allocation", "page", "l1_before", "l1_after",
                     "protect_result", "call_result", "restore_result", "freed")
            record("private_probe_report", **dict(zip(names, map(hex, fields))))
            _, status, raw, aligned, before, after, protect, value, restore, freed = fields
            if not (status == 2 and protect == restore == 0 and value == 0x51a7 and freed == 1
                    and 0x0172e000 <= raw <= 0x01e10000 and raw <= aligned
                    and aligned % 4096 == 0 and aligned+4096 <= raw+8192
                    and before == (aligned & ~0xfffff) | 0x16c16 and after & 3 == 1):
                record("private_probe_incomplete", reboot_required=True)
                raise RuntimeError("Private execution/ownership restoration not established")
            coarse = after & ~0x3ff
            # 000581cc..00058204 bounds a 512-entry pool at 0009c000.
            if not 0x9c000 <= coarse < 0x11c000:
                raise RuntimeError("Unexpected native coarse-table allocation")
            if protocol.read(L1 + (aligned >> 20)*4, 4) != struct.pack("<I", after):
                raise RuntimeError("Heap L1 differs from reported mapping")
            restored = protocol.read(coarse, 1024)
            (folder / "heap_l2_after.bin").write_bytes(restored)
            words = struct.unpack("<256I", restored)
            for index, descriptor in enumerate(words):
                virtual = (aligned & ~0xfffff) + index*4096
                expected = ((virtual & ~0xffff) | 0xe435) if descriptor & 3 == 1 else virtual | 0x5b7
                if descriptor != expected:
                    raise RuntimeError("Heap permissions not restored to identity RW/XN")
                if descriptor & 3 == 1 and words[index & ~15:(index & ~15)+16] != (descriptor,)*16:
                    raise RuntimeError("Inconsistent large-page descriptor group")
            record("private_execution_verified", return_value=hex(value), freed=True,
                   full_heap_section_permissions_restored=True,
                   stock_coarse_table_retained=hex(coarse), exact_topology_restored=False)
        if payload_name in INSTALL_PROBES:
            fields=struct.unpack('<16I',protocol.read(SCRATCH+0x180,64))
            names=('magic','status','allocation','code','data','code_size','state_offset',
                   'rx_result','write_result','ro_result','installed','usb_guard_offset','usb_branch',
                   'usb_write_result','usb_ro_result','usb_installed')
            record('installation_report',**dict(zip(names,map(hex,fields))))
            _,status,raw,code,data,length,offset,rx,write,ro,installed,guard_offset,branch,usb_write,usb_ro,usb_installed=fields
            hook=bytearray((OUT/'rec_lifecycle_hook.bin').read_bytes())
            expected_offset=hook.index(struct.pack('<I',0xdeadbeef))
            symbols=next(x for x in json.loads((OUT/'build_manifest.json').read_text()) if x['name']=='rec_lifecycle_hook')['symbols']
            expected_branch=0x0b000000|(((code+symbols['usb_attach_guard']-0x02240d8c)>>2)&0xffffff)
            if not (status==2 and installed==usb_installed==1 and rx==write==ro==usb_write==usb_ro==0 and
                    0x01c00000<=raw<=0x01cfd000 and raw<=code and code%4096==0 and
                    data==code+4096 and data+4096<=raw+12288 and
                    length==len(hook) and offset==expected_offset and guard_offset==symbols['usb_attach_guard'] and branch==expected_branch):
                raise RuntimeError('Passive hook installation incomplete; retain journal and cold restart')
            struct.pack_into('<I',hook,offset,data)
            if protocol.read(code,length)!=bytes(hook):
                raise RuntimeError('Private hook code readback mismatch')
            if protocol.read(0x02581e78,4)!=struct.pack('<I',code):
                raise RuntimeError('Hook slot did not point to owned code')
            if protocol.read(L1+0x25*4,4)!=struct.pack('<I',0x0251ec16):
                raise RuntimeError('UI table protection not restored')
            if protocol.read(L1+0x22*4,4)!=struct.pack('<I',0x0221ec06):
                raise RuntimeError('Attach code protection not restored')
            if protocol.read(0x02240d84,4)!=struct.pack('<I',branch):
                raise RuntimeError('Attach branch readback failed')
            if protocol.read(L1+0x1c*4,4)!=struct.pack('<I',0xa0401):
                raise RuntimeError('Heap mapping changed unexpectedly')
            if protocol.read(0xa0400+((code>>12)&255)*4,4)!=struct.pack('<I',code|0x7b6):
                raise RuntimeError('Code page is not read-only/executable')
            values=struct.unpack('<16I',protocol.read(data,64))
            if values[:7]!=(0x52454348,2,raw,code,data,0,0) or values[10:14]!=(0x1e670d0,12,7,0):
                raise RuntimeError('Passive hook state invalid')
            arena={'allocation':raw,'bytes':12288,'code':code,'state':data,
                   'code_sha256':hashlib.sha256(hook).hexdigest(),'enabled':False,
                   'state_version':2,'usb_branch':branch,
                   'lifetime':'retained until cold restart; never free while reachable'}
            (folder/'owned_arena.json').write_text(json.dumps(arena,indent=2)+'\n')
            record('passive_hook_verified',**arena,mode_changed=False,
                   ui_table_permissions_restored=True)
            if payload_name == 'rec_install_label_probe':
                from movie_bitrate_label import blob, CODE, CHANGES
                label=blob()
                receipt=struct.unpack('<8I',protocol.read(SCRATCH+0x1c0,32))
                if receipt!=(0x4c414231,2,0,0,4,0,0,0x03e16c06):
                    raise RuntimeError('Label installation incomplete; cold restart required')
                if protocol.read(CODE,len(label))!=label:
                    raise RuntimeError('Immutable label code/resource readback mismatch')
                expected=bytearray(label_before)
                for address,original,new in CHANGES:
                    if struct.unpack_from('<I',expected,address-0x03eb6000)[0]!=original:
                        raise RuntimeError('Original graphics page inconsistent')
                    struct.pack_into('<I',expected,address-0x03eb6000,new)
                after=protocol.read(0x03eb6000,4096)
                (folder/'graphics_page_patched.bin').write_bytes(after)
                if after!=expected or protocol.read(L1+0x3e*4,4)!=struct.pack('<I',0x03e16c06):
                    raise RuntimeError('Graphics changes or original permissions differ')
                details={'status':'installed_in_jig_not_visually_accepted','label_sha256':hashlib.sha256(label).hexdigest(),
                         'code':hex(CODE),'bytes':len(label),'changes':CHANGES,
                         'scope':'movie menu id 0x88/type4, MSG_VALM_ISO_400 only; ordinary ISO remains native',
                         'lifetime':'part of retained arena; cold restart retires this provider'}
                (folder/'label_resources.json').write_text(json.dumps(details,indent=2)+'\n')
                record('label_provider_verified',**details)
        success = True
    finally:
        if protocol.healthy:
            if armed:
                protocol.write(ROOT_PTR, struct.pack("<I", TABLE))
                protocol.write(CALLBACK, bytes(4))
                if protocol.read(ROOT_PTR, 4) != struct.pack("<I", TABLE) or protocol.read(CALLBACK, 4) != bytes(4):
                    raise RuntimeError("Host control restoration failed")
                record("host_controls_restored")
            if scratch_changed:
                if executed and protocol.read(L2, 1024) != saved_l2:
                    record("permission_restore_unconfirmed", cold_restart_required=True)
                    raise RuntimeError("Native permissions not restored; no second execution")
                protocol.write(SCRATCH, snapshot)
                if protocol.read(SCRATCH, 4096) != snapshot:
                    raise RuntimeError("Scratch restoration failed")
                record("scratch_restored", bytes=4096, readback_verified=True)
            if debug_changed:
                protocol.debug(0)
                record("debug_restored", value=0, readback_verified=True)
        else:
            record("transport_uncertain", further_commands=0, cold_restart_required=True)
    return success


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--payload", choices=PROBES, default="loader_probe")
    args = parser.parse_args()
    table, page = preflight(args.payload)
    if not args.execute:
        print(json.dumps({"preflight": "passed", "payload": args.payload,
                          "scope": {"loader_probe": "single-shot RAM marker",
                                    "allocator_probe": "native malloc/align/zero/free round trip",
                                    "private_exec_probe": "native private malloc/RX/execute/RW-XN/free round trip",
                                    "rec_install_probe": "install disabled UI callback; retain 12 KiB until restart",
                                    "rec_install_label_probe": "cold Jig only: disabled REC callback plus scoped 400Mbps resource provider; retain 12 KiB until restart"}[args.payload],
                          "native_protection_changes": {"private_exec_probe":"log-page XN toggle plus stock heap section split",
                                                         "rec_install_probe":"owned code page RX; UI data section temporarily RW then RO; USB code section temporarily RWX then RX; log page restored",
                                                         "rec_install_label_probe":"owned code page RX; UI/USB permissions restored; font prologues changed only before REC; original graphics RWX map restored"}.get(args.payload,"one existing page XN off then on"),
                          "flash_fps_or_mode_writes": False}, indent=2))
        return 0
    sys.path.insert(0, str(PROJECT / "vendor/fffw/ff80"))
    import usb1
    import fftlib
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = OUT / f"{args.payload}_{stamp}"
    folder.mkdir()
    log = {"utc": stamp, "payload": args.payload, "events": [], "status": "running", "flash_fps_or_mode_writes": False}
    protocol = None
    handle = None

    def record(event, **fields):
        log["events"].append({"event": event, **fields})
        (folder / "journal.json").write_text(json.dumps(log, indent=2) + "\n")
        print(event, json.dumps(fields), flush=True)

    try:
        with usb1.USBContext() as context:
            devices = [d for d in context.getDeviceList(skip_on_error=True)
                       if (d.getVendorID(), d.getProductID()) == (0x04CB, 0xFF80)]
            if len(devices) != 1:
                raise RuntimeError("Require exactly one Jig camera")
            handle = devices[0].open()
            with handle.claimInterface(0):
                transport = fftlib.ftl(handle)
                transport.ms = 5000
                transport.open_session()
                if len(transport.ping()) != 2 or transport.max_pkt_size < 256:
                    raise RuntimeError("Unexpected transport handshake")
                protocol = GuardedProtocol(transport, record)
                record("session_ready")
                try:
                    if run_probe(protocol, folder, record, table, page, args.payload):
                        log["status"] = {"rec_install_probe":"passive_hook_installed",
                                         "rec_install_label_probe":"passive_hook_installed",
                                         "private_exec_probe":"probe_passed_permissions_restored"}.get(args.payload,"probe_passed_and_restored")
                finally:
                    if protocol.healthy:
                        protocol.healthy = False
                        transport.close_session()
                        protocol.healthy = True
                        record("session_closed")
    except Exception as exc:
        log["status"] = "stopped_on_error"
        record("error", type=type(exc).__name__, message=str(exc))
    finally:
        if handle is not None:
            handle.close()
        record("finished", status=log["status"])
        print("RESULT", folder)
    return 0 if log["status"] in ("probe_passed_and_restored","probe_passed_permissions_restored","passive_hook_installed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
