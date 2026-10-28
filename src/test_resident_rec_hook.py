"""One bounded passive UI test tied to a specific successful installation."""
import argparse
from datetime import datetime,timezone
import hashlib,json,struct,sys,time
from pathlib import Path
from activate_rec_lifecycle import ActivationProtocol,KEY_CALLBACK,PARSER,SLOT
from try_loader_probe import PROJECT,OUT


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('installation',type=Path)
    p.add_argument('--execute',action='store_true');args=p.parse_args()
    arena=json.loads((args.installation/'owned_arena.json').read_text())
    if arena.get('state_version')!=2:raise ValueError('Requires revision 2')
    code=bytearray((OUT/'rec_lifecycle_hook.bin').read_bytes())
    at=code.index(struct.pack('<I',0xdeadbeef));struct.pack_into('<I',code,at,arena['state'])
    if hashlib.sha256(code).hexdigest()!=arena['code_sha256']:raise ValueError('Artifact mismatch')
    if not args.execute:
        print('Preflight passed: disabled hook only, one event, same-session restoration');return 0
    sys.path.insert(0,str(PROJECT/'vendor/fffw/ff80'));import usb1,fftlib
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    path=OUT/f'passive_hook_{stamp}.json'
    report={'status':'running','installation':str(args.installation.resolve()),
            'code_sha256':arena['code_sha256'],'events':[],'fps_or_flash_writes':False}
    def record(e,**kw):
        report['events'].append({'event':e,**kw});path.write_text(json.dumps(report,indent=2)+'\n');print(e,json.dumps(kw),flush=True)
    handle=None;protocol=None;debug=callback=False
    try:
        with usb1.USBContext() as ctx:
            devices=[d for d in ctx.getDeviceList(skip_on_error=True) if (d.getVendorID(),d.getProductID())==(0x04cb,0xff80)]
            if len(devices)!=1:raise RuntimeError('Require one Jig device')
            handle=devices[0].open()
            with handle.claimInterface(0):
                transport=fftlib.ftl(handle);transport.ms=5000;transport.open_session()
                if len(transport.ping())!=2:raise RuntimeError('Invalid handshake')
                protocol=ActivationProtocol(transport,record,arena['state'])
                try:
                    if protocol.debug()!=0:raise RuntimeError('Expected debug flag 0')
                    debug=True;protocol.debug(1)
                    if protocol.read(0x01780590,12)!=bytes(12):raise RuntimeError('Debug callbacks already active')
                    if protocol.read(0x01b6a020,1)!=b'\x07' or protocol.read(0x01b7b518,1)!=b'\x0c':raise RuntimeError('Not Jig')
                    if protocol.read(SLOT,4)!=struct.pack('<I',arena['code']) or protocol.read(arena['code'],len(code))!=bytes(code):raise RuntimeError('Resident code mismatch')
                    before=struct.unpack('<24I',protocol.read(arena['state'],96))
                    if before[:7]!=(0x52454348,2,arena['allocation'],arena['code'],arena['state'],0,0):raise RuntimeError('Hook is not disabled')
                    record('guarded_disabled_state',calls=before[7])
                    callback=True;protocol.write(KEY_CALLBACK,struct.pack('<I',PARSER))
                    if protocol.read(KEY_CALLBACK,4)!=struct.pack('<I',PARSER):raise RuntimeError('Callback readback failed')
                    command=b'MODE REC\n';record('dispatch_once',hook_enabled=False)
                    protocol.transaction(0x200001,5,struct.pack('<4I',0,0,0,len(command)),payload=command)
                    protocol.write(KEY_CALLBACK,bytes(4))
                    if protocol.read(KEY_CALLBACK,4)!=bytes(4):raise RuntimeError('Callback restore failed')
                    callback=False;time.sleep(0.15)
                    after=struct.unpack('<24I',protocol.read(arena['state'],96))
                    record('state_after',words=[hex(x) for x in after])
                    if after[5:7]!=(0,0) or after[7]<=before[7] or after[8]!=0x3001 or after[13]!=0 or after[15]!=0:
                        raise RuntimeError('Passive UI consumption not established')
                    if protocol.read(0x01b6a020,1)!=b'\x07' or protocol.read(0x01b7b518,1)!=b'\x0c':raise RuntimeError('Unexpected mode change')
                    report.update(status='passed',phase=0,calls_before=before[7],calls_after=after[7],last_event='0x3001',mode_change_requested=False)
                finally:
                    if protocol.healthy:
                        if callback:
                            protocol.write(KEY_CALLBACK,bytes(4))
                            if protocol.read(KEY_CALLBACK,4)!=bytes(4):raise RuntimeError('Callback restore failed')
                        if debug:protocol.debug(0)
                        protocol.healthy=False;transport.close_session();protocol.healthy=True
                        record('controls_restored_session_closed')
                    else:record('transport_uncertain',further_commands=0)
    except Exception as exc:
        report['status']='stopped_on_error';record('error',message=str(exc))
    finally:
        if handle is not None:handle.close()
        record('finished',status=report['status'])
        if report['status']=='passed':(OUT/'passive_hook_test.json').write_text(json.dumps(report,indent=2)+'\n')
        print('RESULT',path)
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
