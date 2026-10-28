"""One UI-thread transition request using the verified, installed RAM hook.

Default: offline artifact checks. --execute arms exactly one request. Stock
vendor deinit stops USB; after dispatch there are NO cleanup/close-session
commands on the old transport. Keep f7=1 for the next genuine debug attach.
Cold restart removes the whole experiment if transition/reconnect fails.
"""
import argparse
from datetime import datetime,timezone
import hashlib
import json
from pathlib import Path
import struct
import sys

from try_loader_probe import GuardedProtocol,ApplicationError,PROJECT,OUT
from try_native_rec_callback import preflight as parser_preflight

KEY_CALLBACK,PARSER,SLOT=0x01780598,0x02242b94,0x02581e78


def preflight(folder):
    arena=json.loads((folder/'owned_arena.json').read_text())
    if arena.get('state_version')!=2:raise ValueError('This runner requires verified revision 2')
    installation=json.loads((folder/'journal.json').read_text())
    if installation['status']!='passive_hook_installed': raise ValueError('No completed installation')
    passive=json.loads((OUT/'passive_hook_test.json').read_text())
    if (passive['status']!='passed' or passive['phase']!=0 or
        passive.get('installation')!=str(folder.resolve()) or
        passive.get('code_sha256')!=arena['code_sha256']):
        raise ValueError('No passive UI verification for THIS installation')
    report=json.loads((OUT/'rec_lifecycle_emulation.json').read_text())
    code=bytearray((OUT/'rec_lifecycle_hook.bin').read_bytes())
    if report['status']!='passed' or hashlib.sha256(code).hexdigest()!=report['hook_sha256']:
        raise ValueError('Hook differs from simulated artifact')
    needle=struct.pack('<I',0xdeadbeef)
    if code.count(needle)!=1: raise ValueError('State relocation invalid')
    struct.pack_into('<I',code,code.index(needle),arena['state'])
    if hashlib.sha256(code).hexdigest()!=arena['code_sha256']: raise ValueError('Installed artifact differs')
    parser_preflight()
    return arena,bytes(code)


class ActivationProtocol(GuardedProtocol):
    def __init__(self,transport,record,state):
        super().__init__(transport,record)
        self.state=state

    def write(self,address,data):
        allowed=(address==KEY_CALLBACK and data in (bytes(4),struct.pack('<I',PARSER))) or (
            address==self.state+20 and data in (bytes(4),struct.pack('<I',1)))
        if not allowed: raise ValueError('Write outside transition ownership')
        self.transaction(0x200001,3,struct.pack('<4I',0,0,address,len(data)),payload=data)


def run_request(protocol,arena,code,record):
    state=arena['state']
    debug_changed=callback_changed=armed=handoff=False
    try:
        if protocol.debug()!=0: raise RuntimeError('Unexpected pre-existing debug flag')
        debug_changed=True
        protocol.debug(1)
        if protocol.read(0x01780590,12)!=bytes(12): raise RuntimeError('Callbacks/logging already active')
        if protocol.read(0x01722bb0,4)!=struct.pack('<I',0x0129d1d0): raise RuntimeError('Event sink changed')
        if protocol.read(0x01b6a020,1)!=b'\x07': raise RuntimeError('Not Jig backend')
        if protocol.read(0x01b7b518,1)!=b'\x0c': raise RuntimeError('Not Jig UI mode')
        if protocol.read(0x02cddeb4,2)!=b'\x0c\0': raise RuntimeError('Not Jig root state')
        if protocol.read(SLOT,4)!=struct.pack('<I',arena['code']): raise RuntimeError('Hook slot changed')
        if protocol.read(0x02240d84,4)!=struct.pack('<I',arena['usb_branch']):raise RuntimeError('Attach guard changed')
        if protocol.read(0x0011c088,4)!=struct.pack('<I',0x0221ec06):raise RuntimeError('Attach code not RX')
        if protocol.read(0x0011c070,4)!=struct.pack('<I',0xa0401): raise RuntimeError('Heap mapping changed')
        if protocol.read(0xa0400+((arena['code']>>12)&255)*4,4)!=struct.pack('<I',arena['code']|0x7b6):
            raise RuntimeError('Hook page is not read-only/executable')
        if protocol.read(arena['code'],len(code))!=code: raise RuntimeError('Resident hook code differs')
        values=struct.unpack('<16I',protocol.read(state,64))
        if values[:7]!=(0x52454348,2,arena['allocation'],arena['code'],state,0,0) or values[13]!=0:
            raise RuntimeError('Hook not in clean disabled state')
        if protocol.read(0x0011c094,4)!=struct.pack('<I',0x0251ec16): raise RuntimeError('UI table not RO/XN')
        record('live_guards_passed',calls=values[7],ui_mode=12,backend=7)
        callback_changed=True
        protocol.write(KEY_CALLBACK,struct.pack('<I',PARSER))
        if protocol.read(KEY_CALLBACK,4)!=struct.pack('<I',PARSER): raise RuntimeError('Parser callback readback')
        armed=True
        protocol.write(state+20,struct.pack('<I',1))
        if protocol.read(state+20,4)!=struct.pack('<I',1): raise RuntimeError('Arming readback')
        command=b'MODE REC\n'
        record('dispatch_once',command=command.decode(),expected_usb_stop=True)
        handoff=True
        try:
            protocol.transaction(0x200001,5,struct.pack('<4I',0,0,0,len(command)),payload=command)
        except ApplicationError:
            # A complete rejection never reached the mode parser. Restore.
            handoff=False
            raise
        record('request_acknowledged',normal_mode_proven=False)
    finally:
        if handoff:
            record('old_transport_retired',additional_camera_commands=0,
                   debug_flag_intentionally_left=1,normal_mode_proven=False)
        elif protocol.healthy:
            if armed:
                protocol.write(state+20,bytes(4))
                if protocol.read(state+20,4)!=bytes(4): raise RuntimeError('Disarm readback failed')
            if callback_changed:
                protocol.write(KEY_CALLBACK,bytes(4))
                if protocol.read(KEY_CALLBACK,4)!=bytes(4): raise RuntimeError('Callback restore failed')
            if debug_changed: protocol.debug(0)
            record('pre_dispatch_controls_restored')
        else:
            record('transport_uncertain',additional_camera_commands=0)


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('installation',type=Path)
    p.add_argument('--execute',action='store_true')
    args=p.parse_args()
    arena,code=preflight(args.installation)
    if not args.execute:
        print(json.dumps({'preflight':'passed','arena':arena,'scope':'one UI-thread transition; no FPS/Flash writes',
                          'after_dispatch':'retire old transport; verify new USB enumeration and UI'},indent=2))
        return 0
    sys.path.insert(0,str(PROJECT/'vendor/fffw/ff80'))
    import usb1,fftlib
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path=OUT/f'rec_transition_{stamp}.json'
    log={'utc':stamp,'installation':str(args.installation.resolve()),'events':[],
         'status':'running','fps_or_flash_writes':False}
    def record(event,**fields):
        log['events'].append({'event':event,**fields})
        path.write_text(json.dumps(log,indent=2)+'\n')
        print(event,json.dumps(fields),flush=True)
    handle=None
    try:
        with usb1.USBContext() as ctx:
            devices=[d for d in ctx.getDeviceList(skip_on_error=True) if
                     (d.getVendorID(),d.getProductID())==(0x04cb,0xff80)]
            if len(devices)!=1: raise RuntimeError('Require one Jig camera')
            handle=devices[0].open()
            with handle.claimInterface(0):
                transport=fftlib.ftl(handle);transport.ms=5000
                transport.open_session()
                if len(transport.ping())!=2: raise RuntimeError('Invalid handshake')
                protocol=ActivationProtocol(transport,record,arena['state'])
                try:
                    run_request(protocol,arena,code,record)
                    log['status']='request_acknowledged_awaiting_mode_verification'
                finally:
                    retired=any(e['event']=='old_transport_retired' for e in log['events'])
                    if not retired and protocol.healthy:
                        transport.close_session();record('session_closed')
    except Exception as exc:
        log['status']='dispatch_outcome_uncertain' if any(e['event']=='old_transport_retired' for e in log['events']) else 'stopped_before_handoff'
        record('error',type=type(exc).__name__,message=str(exc))
    finally:
        if handle is not None: handle.close()
        record('finished',status=log['status'])
        print('RESULT',path)
    return 0 if log['status'].startswith('request_acknowledged') else 1


if __name__=='__main__': raise SystemExit(main())
