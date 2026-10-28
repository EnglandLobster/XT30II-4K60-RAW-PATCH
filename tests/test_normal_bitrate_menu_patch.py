"""Fault boundaries for multiword publication and retained native output."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import struct
import tempfile
import unittest
from unittest.mock import patch as mock_patch
from research_fixtures import retained_capture

import normal_fps_patch as shared
from normal_bitrate_menu_patch import POLICY, OUTPUT, OUTPUT_SIZE, L1_TARGET, RO, RW, MENU_CURRENT, MENU_ACTIVE
from test_normal_bitrate_patch import BitrateTransport


class MenuTransport(BitrateTransport):
    def __init__(self, failure=None):
        super().__init__(failure)
        self.policy = POLICY
        image = (shared.SOURCE / 'XT30II_FW204_section_00260060.bin').read_bytes()
        offset = POLICY.region_start - 0x01021000
        self.put(POLICY.region_start, image[offset:offset + POLICY.region_size])
        self.put(0x013E13C4, shared.word(0))
        self.put(L1_TARGET, shared.word(RO))
        self.put(MENU_CURRENT, shared.word(0x01525820))
        self.put(MENU_ACTIVE, b'\0')
        self.put(OUTPUT, b'\xa5' * OUTPUT_SIZE)
        self.original_region = self.get(POLICY.region_start, POLICY.region_size)

    def read_cmd(self, length):
        fn = struct.unpack_from('<I', self.requests[-1], 16)[0]
        result = super().read_cmd(length)
        if fn == 5:
            if self.failure == 'output_corrupt':
                self.put(OUTPUT + 0x88, shared.word(0x926))
            elif self.failure == 'partial_publication':
                address, original, _ = POLICY.changes[-1]
                self.put(address, shared.word(original))
            elif self.failure == 'menu_mapping':
                self.put(L1_TARGET, shared.word(RW))
        return result


class MenuPatchTests(unittest.TestCase):
    def run_case(self, camera, action):
        record = lambda *args, **kwargs: None
        protocol = shared.PatchProtocol(camera, record)
        arena = {'code_sha256': hashlib.sha256(camera.get(shared.CODE, 836)).hexdigest()}
        with mock_patch.object(shared, 'capture', retained_capture), tempfile.TemporaryDirectory() as path:
            shared.run_patch(protocol, arena, action, Path(path), record, POLICY)

    def test_probe_never_publishes_or_changes_output(self):
        camera = MenuTransport()
        self.run_case(camera, 'probe')
        self.assertEqual(camera.get(POLICY.region_start, POLICY.region_size), camera.original_region)
        self.assertEqual(camera.get(OUTPUT, OUTPUT_SIZE), b'\xa5' * OUTPUT_SIZE)
        self.assertEqual(camera.get(shared.STATE, 4096), camera.initial_state)

    def test_apply_and_restore_four_pointers_keep_published_storage_owned(self):
        camera = MenuTransport()
        self.run_case(camera, 'apply')
        expected = bytearray(camera.original_region)
        for address, _, replacement in POLICY.changes:
            struct.pack_into('<I', expected, address - POLICY.region_start, replacement)
        self.assertEqual(camera.get(POLICY.region_start, POLICY.region_size), expected)
        self.assertEqual(camera.get(OUTPUT, OUTPUT_SIZE), POLICY.owned_output[1])
        self.run_case(camera, 'restore')
        self.assertEqual(camera.get(POLICY.region_start, POLICY.region_size), camera.original_region)
        self.assertEqual(camera.get(OUTPUT, OUTPUT_SIZE), POLICY.owned_output[1])
        self.assertEqual(camera.get(shared.STATE, 4096), camera.initial_state)

    def test_timeout_sends_zero_followup_commands(self):
        camera = MenuTransport('timeout')
        with self.assertRaises(TimeoutError):
            self.run_case(camera, 'apply')
        self.assertEqual(len(camera.requests), camera.failed_request_count)

    def test_rejection_restores_staging_without_publication(self):
        camera = MenuTransport('reject')
        with self.assertRaises(shared.ApplicationError):
            self.run_case(camera, 'apply')
        self.assertEqual(camera.get(shared.STATE, 4096), camera.initial_state)
        self.assertEqual(camera.get(POLICY.region_start, POLICY.region_size), camera.original_region)
        self.assertEqual(camera.get(OUTPUT, OUTPUT_SIZE), b'\xa5' * OUTPUT_SIZE)

    def test_failed_output_or_partial_pointers_never_erase_evidence(self):
        for failure in ('native', 'extra_write', 'settings_change', 'output_corrupt',
                        'partial_publication', 'menu_mapping'):
            with self.subTest(failure=failure):
                camera = MenuTransport(failure)
                with self.assertRaises(RuntimeError):
                    self.run_case(camera, 'apply')
                self.assertNotEqual(camera.get(shared.STATE + 0x100, 0xF00), camera.initial_state[0x100:])
                self.assertEqual(camera.execution_count, 1)
                self.assertEqual(struct.unpack_from('<I', camera.requests[-1], 16)[0], 2)

    def test_active_menu_bad_source_or_missing_policy_blocks_every_write(self):
        for address, value in ((MENU_ACTIVE, 1), (L1_TARGET, RW),
                               (0x013E13C4, 1), (0x000A047C, OUTPUT | 0x7B6),
                               (0x01525824, 0x3C4), (POLICY.changes[-1][0], 0)):
            with self.subTest(address=hex(address)):
                camera = MenuTransport()
                camera.put(address, shared.word(value))
                with self.assertRaises(RuntimeError):
                    self.run_case(camera, 'apply')
                self.assertEqual(camera.execution_count, 0)
                self.assertFalse(any(struct.unpack_from('<I', req, 16)[0] == 3 for req in camera.requests))

    def test_host_write_whitelist_does_not_expand_to_output_or_menu(self):
        camera = MenuTransport()
        protocol = shared.PatchProtocol(camera, lambda *args, **kwargs: None)
        for address in (OUTPUT, OUTPUT + OUTPUT_SIZE - 4, L1_TARGET, MENU_CURRENT,
                        *[change[0] for change in POLICY.changes]):
            with self.assertRaises(ValueError):
                protocol.write(address, shared.word(0))
        self.assertEqual(camera.requests, [])

    def test_preflight_rejects_output_outside_retained_tail(self):
        with tempfile.TemporaryDirectory() as path:
            install = Path(path)
            (install / 'owned_arena.json').write_text(json.dumps({'allocation': shared.RAW,
                'code': shared.CODE, 'state': shared.STATE, 'state_version': 2, 'bytes': 12288}))
            for address, data in ((shared.STATE, b'\0'), (shared.CODE, b'\0'),
                                  (shared.RAW + 12288, b'\0'), (OUTPUT, bytes(4096))):
                with self.subTest(address=hex(address), length=len(data)):
                    with self.assertRaisesRegex(ValueError, 'retained allocation tail'):
                        shared.preflight(install, 'probe', replace(POLICY, owned_output=(address, data)))


if __name__ == '__main__':
    unittest.main()
