"""Host failure boundaries; native payload/MMU behavior is checked separately."""
from pathlib import Path
import hashlib
import struct
import tempfile
import unittest
from unittest.mock import patch as mock_patch
from research_fixtures import retained_capture
from test_loader_probe import FakeTransport
import normal_fps_patch as patch


class NormalTransport(FakeTransport):
    def __init__(self,failure=None,policy=patch.FPS_POLICY):
        super().__init__(failure)
        self.policy=policy
        self.debug_flag=1
        image=(patch.SOURCE/'XT30II_FW204_section_00260060.bin').read_bytes()
        for a,n in ((patch.CODE,836),(patch.STATE,4096),(patch.HEAP_L2,1024),(patch.RULE_L2,1024)):
            self.put(a,retained_capture(a,n))
        self.put(policy.region_start,image[policy.region_start-0x01021000:
                                          policy.region_start+policy.region_size-0x01021000])
        if policy.owned_output:
            address, data = policy.owned_output
            self.put(address,b'\xa5'*len(data))
        self.put(0x01780590,struct.pack('<3I',1,patch.NORMAL_CALLBACK,0x02242b94))
        self.put(0x01b7b518,b'\x03');self.put(0x02cddeb4,b'\x03\0')
        self.put(0x0011c070,patch.word(patch.HEAP_L2|1))
        self.put(0x0011c04c,patch.word(patch.RULE_L2|1))
        self.initial_state=self.get(patch.STATE,4096)

    def read_cmd(self,length):
        request=self.requests[-1]
        op,_,_,_,fn=struct.unpack_from('<5I',request)
        if fn!=5:return super().read_cmd(length)
        self.execution_count+=1
        if self.failure=='timeout':
            self.failed_request_count=len(self.requests)
            raise TimeoutError('No complete response')
        if self.failure=='reject':return struct.pack('<5I',op,1,3,0,fn)+request[20:36]
        action=struct.unpack('<I',self.get(patch.REPORT+4,4))[0]
        self.put(patch.ROOT_PTR,patch.word(patch.TABLE))
        self.put(patch.CALLBACK,patch.word(patch.NORMAL_CALLBACK))
        self.put(patch.STATE+12,patch.word(patch.CODE))
        expected=self.policy.replacement if action==2 else self.policy.original
        new=self.policy.replacement if action==1 else self.policy.original
        if action:
            if action==1 and self.policy.owned_output:
                self.put(*self.policy.owned_output)
            for address, original, replacement in self.policy.changes:
                self.put(address,patch.word(replacement if action==1 else original))
        if self.failure=='extra_write':self.put(self.policy.target+4,patch.word(0xdeadbeef))
        self.put(patch.REPORT,struct.pack('<11I',self.policy.magic,action,
            0x80000004 if self.failure=='native' else 2,expected,expected,new,0,0,
            int(action!=0),int(action!=0),int(action!=0)))
        return struct.pack('<5I',op,0,0,0,fn)+request[20:36]


class NormalPatchTests(unittest.TestCase):
    def run_case(self,camera,action):
        events=[]
        record=lambda e,**kw:events.append((e,kw))
        p=patch.PatchProtocol(camera,record)
        arena={'code_sha256':hashlib.sha256(camera.get(patch.CODE,836)).hexdigest()}
        with mock_patch.object(patch, 'capture', retained_capture), tempfile.TemporaryDirectory() as path:
            patch.run_patch(p,arena,action,Path(path),record)
        return events,p

    def test_probe_preserves_fps_callback_flag_and_every_owned_byte(self):
        c=NormalTransport();self.run_case(c,'probe')
        self.assertEqual(c.execution_count,1)
        self.assertEqual(c.get(patch.STATE,4096),c.initial_state)
        self.assertEqual(c.get(patch.TARGET,4),patch.word(3))
        self.assertEqual(c.get(patch.CALLBACK,4),patch.word(patch.NORMAL_CALLBACK))
        self.assertEqual(c.debug_flag,1)

    def test_apply_and_restore_single_word(self):
        c=NormalTransport();self.run_case(c,'apply')
        self.assertEqual(c.get(patch.TARGET,4),patch.word(0x7ffffffe))
        self.run_case(c,'restore')
        self.assertEqual(c.get(patch.TARGET,4),patch.word(3))
        self.assertEqual(c.get(patch.STATE,4096),c.initial_state)

    def test_timeout_has_zero_followup_commands(self):
        c=NormalTransport('timeout')
        with self.assertRaises(TimeoutError):self.run_case(c,'apply')
        self.assertEqual(len(c.requests),c.failed_request_count)
        self.assertEqual(c.execution_count,1)

    def test_complete_rejection_restores_only_owned_controls(self):
        c=NormalTransport('reject')
        with self.assertRaises(patch.ApplicationError):self.run_case(c,'apply')
        self.assertEqual(c.get(patch.STATE,4096),c.initial_state)
        self.assertEqual(c.get(patch.CALLBACK,4),patch.word(patch.NORMAL_CALLBACK))
        self.assertEqual(c.get(patch.ROOT_PTR,4),patch.word(patch.TABLE))
        self.assertEqual(c.get(patch.TARGET,4),patch.word(3))

    def test_native_failure_does_not_erase_unverified_execution_evidence(self):
        c=NormalTransport('native')
        with self.assertRaises(RuntimeError):self.run_case(c,'apply')
        self.assertNotEqual(c.get(patch.STATE+0x100,0xf00),c.initial_state[0x100:])
        self.assertEqual(c.execution_count,1)
        self.assertEqual(struct.unpack_from('<I',c.requests[-1],16)[0],2)

    def test_wrong_mode_never_arms(self):
        c=NormalTransport();c.put(0x01b7b518,b'\x0c')
        with self.assertRaises(RuntimeError):self.run_case(c,'apply')
        self.assertEqual(c.execution_count,0)
        self.assertEqual(c.get(patch.STATE,4096),c.initial_state)

    def test_host_cannot_write_policy_log_state_or_page_tables(self):
        c=NormalTransport();p=patch.PatchProtocol(c,lambda *a,**kw:None)
        for address in (patch.TARGET,0x06b95000,patch.STATE,patch.HEAP_L2):
            with self.assertRaises(ValueError):p.write(address,patch.word(0))
        self.assertEqual(c.requests,[])


if __name__=='__main__':unittest.main()
