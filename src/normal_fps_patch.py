"""Probe/apply/restore compiled policies through the retained private arena.

Default is offline preflight. No USB flag, setting, recording or Flash command.
The live logger is never borrowed. Any uncertain USB result ends all commands.
"""
import argparse
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct
import sys
from typing import Callable

from try_loader_probe import GuardedProtocol, ApplicationError, PROJECT
from verify_loader_probe import OUT, SOURCE, capture, TABLE, ROOT_PTR, CALLBACK, LOADER

STATE, CODE, RAW = 0x01c1e000, 0x01c1d000, 0x01c1cf10
ENTRY, REPORT, CLONE = STATE+0x400, STATE+0x100, STATE+0x200
NORMAL_CALLBACK, TARGET = 0x020a0b54, 0x013e1788
RULE_L2, HEAP_L2 = 0x0009c800, 0x000a0400
ACTIONS = {'probe':0, 'apply':1, 'restore':2}


@dataclass(frozen=True)
class RulePolicy:
    """An exact, code-owned set of words within one verified source region.

    Definitions are code-owned, never supplied as live CLI addresses. Native
    payloads independently enforce their identity, guards and exact target.
    """
    name: str
    target: int
    original: int
    replacement: int
    magic: int
    rule_start: int
    rule_size: int
    guard: Callable | None = None
    region_start: int = 0x013e0000
    region_size: int = 0x10000
    additional_words: tuple[tuple[int, int, int], ...] = ()
    owned_output: tuple[int, bytes] | None = None

    @property
    def changes(self):
        return ((self.target, self.original, self.replacement), *self.additional_words)


FPS_POLICY = RulePolicy('normal_fps', TARGET, 3, 0x7ffffffe, 0x46505331,
                        0x013e16f0, 624)


def word(value):
    return struct.pack('<I', value)


def build_page(snapshot, table, action, policy=FPS_POLICY):
    if len(snapshot)!=4096 or len(table)!=396 or action not in ACTIONS:
        raise ValueError('Invalid owned-page input')
    clone=bytearray(table)
    if struct.unpack_from('<3I',clone,7*36)!=(6,0x01e12000,0x8d9000):
        raise ValueError('Module 6 descriptor changed')
    struct.pack_into('<II',clone,7*36+4,STATE,4096)
    code=(OUT/f'{policy.name}_patch.bin').read_bytes()
    if not code or len(code)>0xc00: raise ValueError('Payload exceeds owned page')
    page=bytearray(snapshot)
    # The loader reads only base+12; no other header field is consumed. The
    # entry stub restores this observational field before doing any C work.
    struct.pack_into('<I',page,12,ENTRY)
    struct.pack_into('<11I',page,0x100,policy.magic,ACTIONS[action],*([0]*9))
    page[0x200:0x200+len(clone)]=clone
    page[0x400:0x400+len(code)]=code
    return bytes(page)


def preflight(installation, action, policy=FPS_POLICY):
    if not (0x01021000 <= policy.region_start <= policy.rule_start
            < policy.rule_start + policy.rule_size <= policy.region_start + policy.region_size
            <= 0x0172e000):
        raise ValueError('Policy region is outside the verified program allocation')
    addresses = [address for address, _, _ in policy.changes]
    if len(set(addresses)) != len(addresses) or any(
            address % 4 or not policy.rule_start <= address <= policy.rule_start + policy.rule_size - 4
            for address in addresses):
        raise ValueError('Policy words overlap or leave the source fingerprint window')
    arena=json.loads((installation/'owned_arena.json').read_text())
    if (arena['allocation'],arena['code'],arena['state'],arena.get('state_version'))!=(RAW,CODE,STATE,2):
        raise ValueError('This artifact is linked for the verified revision 2 allocation')
    if policy.owned_output:
        address, data = policy.owned_output
        if arena.get('bytes') != 12288 or not (
                STATE + 4096 <= address < address + len(data) <= RAW + arena['bytes']):
            raise ValueError('Native output must stay in the retained allocation tail')
    acceptance=json.loads((OUT/'rec_v2_acceptance.json').read_text())
    if (acceptance['status']!='normal_view_and_retained_ram_debug_verified' or
        acceptance['installation']!=installation.name or acceptance['code_sha256']!=arena['code_sha256']):
        raise ValueError('No confirmed REC/debug acceptance for this installation')
    binary=(OUT/f'{policy.name}_patch.bin').read_bytes()
    digest=hashlib.sha256(binary).hexdigest()
    report=json.loads((OUT/f'{policy.name}_emulation.json').read_text())
    if report['status']!='passed' or report['payload_sha256']!=digest:
        raise ValueError('Exact payload must pass original ARM/kernel validation')
    if action=='apply':
        probe=json.loads((OUT/f'{policy.name}_probe_passed.json').read_text())
        if (probe['installation']!=str(installation.resolve()) or
            probe['payload_sha256']!=digest or probe['status']!='probe_verified_and_restored'):
            raise ValueError('This installation must first pass a write-free policy probe')
    return arena, digest


class PatchProtocol(GuardedProtocol):
    def write(self,address,data):
        allowed=STATE+0x100<=address<address+len(data)<=STATE+4096
        if address==STATE+12: allowed=data in (word(CODE),word(ENTRY))
        if address==ROOT_PTR: allowed=data in (word(TABLE),word(CLONE))
        if address==CALLBACK: allowed=data in (word(NORMAL_CALLBACK),word(LOADER))
        if not allowed: raise ValueError('Host write outside owned staging/control fields')
        for offset in range(0,len(data),256):
            chunk=data[offset:offset+256]
            self.transaction(0x200001,3,struct.pack('<4I',0,0,address+offset,len(chunk)),payload=chunk)


def run_patch(p,arena,action,folder,record,policy=FPS_POLICY):
    staged=armed=invoked=verified=False
    snapshot=None
    try:
        if p.debug()!=1: raise RuntimeError('Retained debug flag must already be 1')
        if p.read(0x01780590,12)!=struct.pack('<3I',1,NORMAL_CALLBACK,0x02242b94):
            raise RuntimeError('Normal debug callbacks differ; do not borrow live logging')
        if p.read(0x01b7b518,1)!=b'\x03' or p.read(0x02cddeb4,2)!=b'\x03\0':
            raise RuntimeError('Not current REC UI/root state')
        if p.read(0x01722b84,1)!=b'\x01': raise RuntimeError('SMP rendezvous not ready')
        guarded_state = policy.guard(p) if policy.guard else None
        if p.read(ROOT_PTR,8)!=struct.pack('<2I',TABLE,0x00e201ec):
            raise RuntimeError('Loader roots differ')
        table=p.read(TABLE,396)
        if table!=capture(TABLE,396): raise RuntimeError('Loader descriptors differ')
        if p.read(0x0011c070,4)!=word(HEAP_L2|1) or p.read(0x0011c04c,4)!=word(RULE_L2|1):
            raise RuntimeError('Mapping roots differ')
        heap=p.read(HEAP_L2,1024); rules=p.read(RULE_L2,1024)
        if (struct.unpack_from('<I',heap,0x1d*4)[0]!=CODE|0x7b6 or
            struct.unpack_from('<I',heap,0x1e*4)[0]!=STATE|0x5b7 or
            struct.unpack_from('<16I',rules,0x380)!=(0x013ee635,)*16):
            raise RuntimeError('Owned/rule permissions differ')
        code=p.read(CODE,836)
        if hashlib.sha256(code).hexdigest()!=arena['code_sha256']:
            raise RuntimeError('Retained resident code differs')
        snapshot=p.read(STATE,4096)
        state=struct.unpack_from('<24I',snapshot)
        if (state[:7]!=(0x52454348,2,RAW,CODE,STATE,0,3) or state[13]!=0 or state[15]!=0):
            raise RuntimeError('Resident state is not completed and inactive')
        before=p.read(policy.region_start,policy.region_size)
        expected=policy.replacement if action=='restore' else policy.original
        replacement=policy.replacement if action=='apply' else policy.original
        for address, original, new in policy.changes:
            if struct.unpack_from('<I',before,address-policy.region_start)[0] != (
                    new if action=='restore' else original):
                raise RuntimeError('Policy word is not the exact expected value')
        reference=(SOURCE/'XT30II_FW204_section_00260060.bin').read_bytes()
        offset=policy.rule_start-0x01021000
        expected_rule=bytearray(reference[offset:offset+policy.rule_size])
        for address, original, new in policy.changes:
            struct.pack_into('<I',expected_rule,address-policy.rule_start,
                             new if action=='restore' else original)
        offset=policy.rule_start-policy.region_start
        if before[offset:offset+policy.rule_size]!=expected_rule:
            raise RuntimeError('Complete policy rule differs')
        output_before = None
        if policy.owned_output:
            address, data = policy.owned_output
            output_before = p.read(address,len(data))
            if action=='restore' and output_before != data:
                raise RuntimeError('Published native output differs from this artifact')
            (folder/'owned_output_original.bin').write_bytes(output_before)
        for name,data in [('owned_page_original.bin',snapshot),('heap_l2_original.bin',heap),
                          ('rule_l2_original.bin',rules),('rule_region_original.bin',before)]:
            (folder/name).write_bytes(data)
        page=build_page(snapshot,table,action,policy)
        (folder/'staged_page.bin').write_bytes(page)
        record('live_guards_passed',action=action,expected=hex(expected),replacement=hex(replacement),
               policy=policy.name,target=hex(policy.target),
               policy_write_planned=action!='probe',borrowed_log_bytes=0)
        staged=True
        p.write(STATE+0x100,page[0x100:])
        if p.read(STATE+0x100,0xf00)!=page[0x100:]: raise RuntimeError('Staging readback mismatch')
        armed=True
        p.write(STATE+12,word(ENTRY))
        p.write(ROOT_PTR,word(CLONE))
        p.write(CALLBACK,word(LOADER))
        for address,value in ((STATE+12,ENTRY),(ROOT_PTR,CLONE),(CALLBACK,LOADER)):
            if p.read(address,4)!=word(value): raise RuntimeError('Arming readback mismatch')
        command=b'CMD X\n'
        record('invoke_once',action=action)
        invoked=True
        try:
            p.transaction(0x200001,5,struct.pack('<4I',0,0,0,len(command)),payload=command)
        except ApplicationError:
            invoked=False
            raise
        result=struct.unpack('<11I',p.read(REPORT,44))
        record('native_report',words=[hex(x) for x in result])
        if result[:3]!=(policy.magic,ACTIONS[action],2): raise RuntimeError('Native operation did not complete')
        for address,value in ((STATE+12,CODE),(ROOT_PTR,TABLE),(CALLBACK,NORMAL_CALLBACK)):
            if p.read(address,4)!=word(value): raise RuntimeError('Native control restoration failed')
        if p.read(HEAP_L2,1024)!=heap or p.read(RULE_L2,1024)!=rules:
            raise RuntimeError('Exact mapping restoration failed')
        after=p.read(policy.region_start,policy.region_size)
        (folder/'rule_region_after.bin').write_bytes(after)
        expected_region=bytearray(before)
        for address, original, new in policy.changes:
            struct.pack_into('<I',expected_region,address-policy.region_start,
                             new if action=='apply' else original)
        if after!=expected_region: raise RuntimeError('Unexpected rule-region difference')
        if policy.owned_output:
            address, data = policy.owned_output
            output_after = p.read(address,len(data))
            (folder/'owned_output_after.bin').write_bytes(output_after)
            if output_after != (data if action=='apply' else output_before):
                raise RuntimeError('Native owned output changed unexpectedly')
        if policy.guard and policy.guard(p)!=guarded_state:
            raise RuntimeError('Guarded mode/settings changed during operation')
        # Check all lifecycle data except asynchronous USB observation counters;
        # never overwrite those counters when cleaning unused staging bytes.
        state_after=p.read(STATE,96)
        if state_after[:64]!=snapshot[:64] or state_after[80:]!=snapshot[80:96]:
            raise RuntimeError('Resident lifecycle state changed unexpectedly')
        if p.read(CODE,836)!=code: raise RuntimeError('Resident code changed')
        if p.debug()!=1: raise RuntimeError('Debug flag changed')
        verified=True
        record('operation_verified',policy=policy.name,target=hex(policy.target),
               policy_value=hex(replacement),region_bytes_checked=policy.region_size,
               policy_words_checked=len(policy.changes),
               exact_page_tables_restored=True,resident_code_unchanged=True)
    finally:
        if not p.healthy:
            record('transport_uncertain',additional_commands=0)
        elif not invoked:
            if armed:
                for address,value in ((CALLBACK,NORMAL_CALLBACK),(ROOT_PTR,TABLE),(STATE+12,CODE)):
                    p.write(address,word(value))
                    if p.read(address,4)!=word(value): raise RuntimeError('Predispatch restoration failed')
            if staged:
                p.write(STATE+0x100,snapshot[0x100:])
                if p.read(STATE+0x100,0xf00)!=snapshot[0x100:]: raise RuntimeError('Staging restore failed')
            record('predispatch_controls_restored')
        elif verified:
            p.write(STATE+0x100,snapshot[0x100:])
            if p.read(STATE+0x100,0xf00)!=snapshot[0x100:]: raise RuntimeError('Staging restore failed')
            record('owned_staging_restored',bytes=0xf00,readback_verified=True)
        else:
            record('native_result_unverified',no_cleanup_writes=True)


def main(policy=FPS_POLICY, description=__doc__):
    parser=argparse.ArgumentParser(description=description)
    parser.add_argument('installation',type=Path)
    parser.add_argument('--action',choices=ACTIONS,default='probe')
    parser.add_argument('--execute',action='store_true')
    args=parser.parse_args()
    arena,digest=preflight(args.installation,args.action,policy)
    if not args.execute:
        print(json.dumps({'preflight':'passed','action':args.action,'target':hex(policy.target),
            'persistent_writes':False,'live_logging_untouched':True,'payload_sha256':digest},indent=2))
        return 0
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    folder=OUT/f'{policy.name}_{args.action}_{stamp}';folder.mkdir()
    log={'utc':stamp,'installation':str(args.installation.resolve()),'action':args.action,
         'payload_sha256':digest,'policy':policy.name,'target':hex(policy.target),
         'events':[],'status':'running','persistent_writes':False}
    def record(event,**fields):
        log['events'].append({'event':event,**fields})
        (folder/'journal.json').write_text(json.dumps(log,indent=2)+'\n')
        print(event,json.dumps(fields),flush=True)
    sys.path.insert(0,str(PROJECT/'vendor/fffw/ff80'))
    import usb1,fftlib
    handle=None
    try:
        with usb1.USBContext() as ctx:
            devices=[d for d in ctx.getDeviceList(skip_on_error=False) if
                     (d.getVendorID(),d.getProductID())==(0x04cb,0xff80)]
            if len(devices)!=1: raise RuntimeError('Need exactly one retained-debug camera')
            handle=devices[0].open()
            with handle.claimInterface(0):
                transport=fftlib.ftl(handle);transport.ms=5000
                transport.open_session()
                if len(transport.ping())!=2: raise RuntimeError('Invalid handshake')
                p=PatchProtocol(transport,record)
                try:
                    run_patch(p,arena,args.action,folder,record,policy)
                    log['status']=args.action+'_verified_and_restored'
                finally:
                    if p.healthy:
                        transport.close_session();record('session_closed')
    except Exception as error:
        log['status']='stopped_on_error'
        record('error',type=type(error).__name__,message=str(error))
    finally:
        if handle is not None: handle.close()
        record('finished',status=log['status'])
        print('RESULT',folder)
    if log['status']=='probe_verified_and_restored':
        (OUT/f'{policy.name}_probe_passed.json').write_text(json.dumps(log,indent=2)+'\n')
    return 0 if log['status'].endswith('_verified_and_restored') else 1


if __name__=='__main__': raise SystemExit(main())
