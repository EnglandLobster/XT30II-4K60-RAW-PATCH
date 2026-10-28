"""Bitrate host invariants and fault injection; no USB or device access."""
from pathlib import Path
import hashlib
import json
import struct
import tempfile
import unittest
from unittest.mock import patch as mock_patch
from research_fixtures import retained_capture

import normal_fps_patch as shared
from normal_bitrate_patch import POLICY, TARGET
from test_normal_fps_patch import NormalTransport


class BitrateTransport(NormalTransport):
    def __init__(self, failure=None):
        super().__init__(failure, POLICY)
        source = shared.SOURCE / 'XT30II_FW204_section_00260060.bin'
        self.put(0x01027778, source.read_bytes()[0x6778:0x67F4])
        self.put(0x013E1788, shared.word(0x7FFFFFFE))
        self.put(0x02219ED0, shared.word(0xE3A00006))
        self.put(0x0011C088, shared.word(0x0221EC06))
        self.put(0x02CDDE60, b'\2\7\1\0')
        self.put(0x02E94A30, b'\7')
        self.put(0x02E137E8, bytes(8))
        self.put(0x01B85AD2, b'\4')
        self.put(0x0177F8C0, (shared.OUT / 'normal_resource_apply_20261012T074311333335Z/settings_before.bin').read_bytes())
        self.original_rules = self.get(0x013E0000, 65536)

    def read_cmd(self, length):
        fn = struct.unpack_from('<I', self.requests[-1], 16)[0]
        result = super().read_cmd(length)
        if fn == 5 and self.failure == 'settings_change':
            self.put(0x0177F934, b'\0')
        return result


class BitratePatchTests(unittest.TestCase):
    def run_case(self, camera, action):
        record = lambda *args, **kwargs: None
        protocol = shared.PatchProtocol(camera, record)
        arena = {'code_sha256': hashlib.sha256(camera.get(shared.CODE, 836)).hexdigest()}
        with mock_patch.object(shared, 'capture', retained_capture), tempfile.TemporaryDirectory() as path:
            shared.run_patch(protocol, arena, action, Path(path), record, POLICY)

    def test_probe_preserves_rules_owned_page_and_both_existing_fixes(self):
        camera = BitrateTransport()
        self.run_case(camera, 'probe')
        self.assertEqual(camera.get(0x013E0000, 65536), camera.original_rules)
        self.assertEqual(camera.get(shared.STATE, 4096), camera.initial_state)
        self.assertEqual(camera.get(0x02219ED0, 4), shared.word(0xE3A00006))
        self.assertEqual(camera.execution_count, 1)

    def test_apply_restore_only_the_ceiling_word(self):
        camera = BitrateTransport()
        self.run_case(camera, 'apply')
        expected = bytearray(camera.original_rules)
        struct.pack_into('<I', expected, TARGET - 0x013E0000, 0)
        self.assertEqual(camera.get(0x013E0000, 65536), expected)
        self.run_case(camera, 'restore')
        self.assertEqual(camera.get(0x013E0000, 65536), camera.original_rules)
        self.assertEqual(camera.get(shared.STATE, 4096), camera.initial_state)
        self.assertEqual(camera.debug_flag, 1)

    def test_timeout_sends_no_followup(self):
        camera = BitrateTransport('timeout')
        with self.assertRaises(TimeoutError):
            self.run_case(camera, 'apply')
        self.assertEqual(len(camera.requests), camera.failed_request_count)
        self.assertEqual(camera.execution_count, 1)

    def test_complete_rejection_restores_only_staging_and_controls(self):
        camera = BitrateTransport('reject')
        with self.assertRaises(shared.ApplicationError):
            self.run_case(camera, 'apply')
        self.assertEqual(camera.get(0x013E0000, 65536), camera.original_rules)
        self.assertEqual(camera.get(shared.STATE, 4096), camera.initial_state)
        self.assertEqual(camera.get(shared.ROOT_PTR, 4), shared.word(shared.TABLE))
        self.assertEqual(camera.get(shared.CALLBACK, 4), shared.word(shared.NORMAL_CALLBACK))

    def test_native_failure_extra_write_and_settings_race_keep_evidence(self):
        for failure in ('native', 'extra_write', 'settings_change'):
            with self.subTest(failure=failure):
                camera = BitrateTransport(failure)
                with self.assertRaises(RuntimeError):
                    self.run_case(camera, 'apply')
                self.assertNotEqual(camera.get(shared.STATE + 0x100, 0xF00), camera.initial_state[0x100:])
                self.assertEqual(camera.execution_count, 1)
                self.assertEqual(struct.unpack_from('<I', camera.requests[-1], 16)[0], 2)

    def test_recording_missing_fix_or_stale_fps_blocks_all_writes(self):
        for address, value in ((0x02CDDE60, b'\3'), (0x02E137EC, shared.word(0x02E137F0)),
                               (0x013E1788, shared.word(3)), (0x02219ED0, shared.word(0xE3A00004)),
                               (0x0177F8ED, b'\5'), (0x01B85AD2, b'\6')):
            with self.subTest(address=hex(address)):
                camera = BitrateTransport()
                camera.put(address, value)
                with self.assertRaises(RuntimeError):
                    self.run_case(camera, 'apply')
                self.assertEqual(camera.execution_count, 0)
                self.assertEqual(camera.get(shared.STATE, 4096), camera.initial_state)
                self.assertFalse(any(struct.unpack_from('<I', req, 16)[0] == 3 for req in camera.requests))

    def test_host_cannot_write_ceiling_settings_logger_or_page_tables(self):
        camera = BitrateTransport()
        protocol = shared.PatchProtocol(camera, lambda *args, **kwargs: None)
        for address in (TARGET, 0x0177F934, 0x02219ED0, shared.STATE, shared.RULE_L2, 0x06B95000):
            with self.assertRaises(ValueError):
                protocol.write(address, shared.word(0))
        self.assertEqual(camera.requests, [])

    def test_apply_requires_bitrate_probe_for_the_same_installation_and_payload(self):
        binary = (shared.OUT / 'normal_bitrate_patch.bin').read_bytes()
        digest = hashlib.sha256(binary).hexdigest()
        with tempfile.TemporaryDirectory() as path:
            out = Path(path)
            install = out / 'installation'
            install.mkdir()
            (install / 'owned_arena.json').write_text(json.dumps({'allocation': shared.RAW,
                'code': shared.CODE, 'state': shared.STATE, 'state_version': 2, 'code_sha256': 'resident'}))
            (out / 'rec_v2_acceptance.json').write_text(json.dumps({'status': 'normal_view_and_retained_ram_debug_verified',
                'installation': install.name, 'code_sha256': 'resident'}))
            (out / 'normal_bitrate_patch.bin').write_bytes(binary)
            (out / 'normal_bitrate_emulation.json').write_text(json.dumps({'status': 'passed', 'payload_sha256': digest}))
            good = {'installation': str(install.resolve()), 'payload_sha256': digest,
                    'status': 'probe_verified_and_restored'}
            with mock_patch.object(shared, 'OUT', out):
                for changed in ({'installation': '/previous'}, {'payload_sha256': 'different'},
                                {'status': 'stopped_on_error'}):
                    (out / 'normal_bitrate_probe_passed.json').write_text(json.dumps(good | changed))
                    with self.assertRaises(ValueError):
                        shared.preflight(install, 'apply', POLICY)
                (out / 'normal_bitrate_probe_passed.json').write_text(json.dumps(good))
                self.assertEqual(shared.preflight(install, 'apply', POLICY)[1], digest)


if __name__ == '__main__':
    unittest.main()
