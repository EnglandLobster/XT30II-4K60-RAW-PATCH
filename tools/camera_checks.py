"""Bounded fresh cold-Jig / retained-REC checks. USB access requires --execute."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,struct,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'src'),str(ROOT/'vendor/fffw/ff80')]
from try_loader_probe import GuardedProtocol,OUT,SOURCE

def digest(data):return hashlib.sha256(data).hexdigest()

def checked_session(callback, *, cold=False):
    import usb1,fftlib
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=OUT/('cold_check_' if cold else 'rec_check_');folder=folder.with_name(folder.name+stamp);folder.mkdir()
    log={'status':'running','events':[],'utc':stamp};handle=None;protocol=None
    def record(event,**kw):
        log['events'].append({'event':event,**kw})
        (folder/'journal.json').write_text(json.dumps(log,indent=2)+'\n')
    try:
        with usb1.USBContext() as ctx:
            devices=[d for d in ctx.getDeviceList(skip_on_error=True) if (d.getVendorID(),d.getProductID())==(0x04cb,0xff80)]
            if len(devices)!=1:raise RuntimeError('Require exactly one 04cb:ff80 camera')
            handle=devices[0].open()
            with handle.claimInterface(0):
                t=fftlib.ftl(handle);t.ms=5000;t.open_session()
                if len(t.ping())!=2:raise RuntimeError('Bad handshake')
                protocol=GuardedProtocol(t,record);changed=False
                try:
                    if protocol.debug()!=(0 if cold else 1):raise RuntimeError('Wrong lifecycle debug flag; cold-restart and begin again')
                    if cold:changed=True;protocol.debug(1)
                    callback(protocol,folder,record)
                    log['status']='passed'
                finally:
                    if protocol.healthy:
                        if changed:protocol.debug(0)
                        protocol.healthy=False;t.close_session();protocol.healthy=True
                        record('session_closed')
                    else:record('transport_uncertain',further_commands=0)
    except Exception as error:
        log['status']='failed';record('error',message=str(error));raise
    finally:
        if handle is not None:handle.close()
        record('finished',status=log['status'])
    return folder

def cold_check():
    checks=json.loads((ROOT/'metadata/cold-checks.json').read_text())
    # Include original execution entry points used by the loader and REC path.
    extra=((0x129c05c,0x94),(0x129ca08,0x50),(0x128b9b0,0x340),(0x11898c4,0x130),
           (0x209aa94,0x2e8),(0x57dcc,0x1134),(0x13d77a4,0x234c),(0x129d1d0,0x118),
           (0x2242b94,0x13c),(0x129c708,0xa4),(0x1e2cedc,316),(0x2581bd0,692),
           (0x252b91c,3752),(0x1e670d0,120),(0x1e66180,620))
    from verify_loader_probe import capture
    from movie_bitrate_label import FONT_WINDOW,FONT_SIZE,FONT_SHA256
    for address,size in extra:checks.append({'address':hex(address),'bytes':size,'sha256':digest(capture(address,size))})
    checks.append({'address':hex(FONT_WINDOW),'bytes':FONT_SIZE,'sha256':FONT_SHA256})
    def collect(p,folder,record):
        for item in checks:
            address=int(item['address'],0);d=p.read(address,item['bytes'])
            if digest(d)!=item['sha256']:raise RuntimeError('Unsupported cold firmware/state at '+item['address'])
            record('checked',address=item['address'],bytes=len(d))
    return checked_session(collect,cold=True)

def verify_rec(installation):
    arena=json.loads((installation/'owned_arena.json').read_text())
    if (arena['allocation'],arena['code'],arena['state'],arena['state_version'])!=(0x1c1cf10,0x1c1d000,0x1c1e000,2):raise RuntimeError('Unsupported owned arena')
    (OUT/'rec_v2_acceptance.json').unlink(missing_ok=True)
    checks=json.loads((ROOT/'metadata/rec-checks.json').read_text())
    def collect(p,folder,record):
        for item in checks:
            address=int(item['address'],0);d=p.read(address,item['bytes'])
            if address==arena['state']:
                words=struct.unpack('<24I',d)
                if words[:7]!=(0x52454348,2,arena['allocation'],arena['code'],arena['state'],0,3) or words[13] or words[15]:raise RuntimeError('Lifecycle is not complete and inactive')
            elif digest(d)!=item['sha256']:raise RuntimeError('REC state/code mismatch at '+item['address'])
            record('checked',address=item['address'],bytes=len(d))
        result={'status':'normal_view_and_retained_ram_debug_verified','installation':installation.name,
                'code_sha256':arena['code_sha256'],'user_confirmed_no_restart_and_live_view':True}
        (folder/'acceptance.json').write_text(json.dumps(result,indent=2)+'\n')
    folder=checked_session(collect)
    # Publish acceptance only after the healthy session has closed successfully.
    (OUT/'rec_v2_acceptance.json').write_bytes((folder/'acceptance.json').read_bytes())
    return folder

def fingerprints():
    from audit_movie_buffer_profiles import live_validation_plan
    (OUT/'resource_fingerprints.json').unlink(missing_ok=True)
    checks=live_validation_plan()['fingerprints'];result={'status':'running','checks':[]}
    def collect(p,folder,record):
        for item in checks:
            d=p.read(int(item['address'],0),item['size'])
            if digest(d)!=item['reference_sha256']:raise RuntimeError('Resource fingerprint mismatch at '+item['address'])
            name=f"window_{int(item['address'],0):08x}_public_fingerprint.bin"
            (SOURCE/name).write_bytes(d)
            (SOURCE/name).with_suffix('.json').write_text(json.dumps({'status':'success','fresh_live_read':True})+'\n')
            result['checks'].append({'address':item['address'],'file':name,'sha256':digest(d)})
            record('checked',address=item['address'],bytes=len(d))
    folder=checked_session(collect);result['status']='passed'
    (OUT/'resource_fingerprints.json').write_text(json.dumps(result,indent=2)+'\n')
    return folder

def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('action',choices=['cold','rec','fingerprints']);ap.add_argument('installation',type=Path,nargs='?');ap.add_argument('--execute',action='store_true');ap.add_argument('--live-view-confirmed',action='store_true');a=ap.parse_args()
    if not a.execute:print('No USB access. Add --execute only at the matching step in docs/INSTALL.md.');return
    if a.action=='rec':
        if not a.installation or not a.live_view_confirmed:ap.error('REC requires installation and --live-view-confirmed after physical verification')
        print(verify_rec(a.installation.resolve()))
    elif a.action=='cold':print(cold_check())
    else:print(fingerprints())
if __name__=='__main__':main()
