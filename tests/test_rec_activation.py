"""Transition handoff never cleans up against a possibly stopping USB task."""
from pathlib import Path
import struct
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from test_loader_probe import FakeTransport
import activate_rec_lifecycle as activation


class RecActivationTests(unittest.TestCase):
    def setup_case(self,failure=None):
        camera=FakeTransport(failure)
        arena={'allocation':0x1c1cf10,'code':0x1c1d000,'state':0x1c1e000,'usb_branch':0x0be77800}
        code=b'checked artifact'
        fields=(0x52454348,2,arena['allocation'],arena['code'],arena['state'],0,0,1,
                0x3001,0,0x1e670d0,12,7,0,0,0)
        for adr,data in ((arena['code'],code),(arena['state'],struct.pack('<16I',*fields)),
                         (activation.SLOT,struct.pack('<I',arena['code'])),
                         (0x01722bb0,struct.pack('<I',0x0129d1d0)),(0x01b7b518,b'\x0c'),
                         (0x02cddeb4,b'\x0c\0'),(0x0011c094,struct.pack('<I',0x0251ec16)),
                         (0x0011c088,struct.pack('<I',0x0221ec06)),
                         (0x02240d84,struct.pack('<I',arena['usb_branch'])),
                         (0x0011c070,struct.pack('<I',0xa0401)),
                         (0xa0400+((arena['code']>>12)&255)*4,struct.pack('<I',arena['code']|0x7b6))):
            camera.put(adr,data)
        events=[]
        record=lambda e,**kw:events.append((e,kw))
        protocol=activation.ActivationProtocol(camera,record,arena['state'])
        return camera,arena,code,events,record,protocol

    def test_success_has_zero_commands_after_dispatch_and_keeps_attach_flag(self):
        c,a,code,events,record,p=self.setup_case()
        activation.run_request(p,a,code,record)
        self.assertEqual(struct.unpack_from('<I',c.requests[-1],16)[0],5)
        self.assertEqual(c.execution_count,1)
        self.assertEqual(c.debug_flag,1)
        self.assertEqual(events[-1][0],'old_transport_retired')

    def test_timeout_has_zero_additional_commands(self):
        c,a,code,events,record,p=self.setup_case('timeout')
        with self.assertRaises(TimeoutError): activation.run_request(p,a,code,record)
        self.assertEqual(len(c.requests),c.failed_request_count)
        self.assertFalse(p.healthy)
        self.assertEqual(c.execution_count,1)
        self.assertEqual(events[-1][0],'old_transport_retired')

    def test_complete_rejection_disarms_and_restores(self):
        c,a,code,events,record,p=self.setup_case('reject')
        with self.assertRaises(activation.ApplicationError): activation.run_request(p,a,code,record)
        self.assertEqual(c.debug_flag,0)
        self.assertEqual(c.get(a['state']+20,4),bytes(4))
        self.assertEqual(c.get(activation.KEY_CALLBACK,4),bytes(4))
        self.assertNotIn('old_transport_retired',[e[0] for e in events])

    def test_changed_resident_code_prevents_dispatch(self):
        c,a,code,events,record,p=self.setup_case()
        c.put(a['code'],b'corrupted')
        with self.assertRaises(RuntimeError): activation.run_request(p,a,code,record)
        self.assertEqual(c.execution_count,0)
        self.assertEqual(c.debug_flag,0)
        self.assertEqual(c.get(a['state']+20,4),bytes(4))

    def test_cannot_write_video_parameters(self):
        c,a,code,events,record,p=self.setup_case()
        with self.assertRaises(ValueError): p.write(0x13e1788,bytes(4))
        self.assertEqual(c.requests,[])


if __name__=='__main__':unittest.main()
