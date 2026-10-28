"""Host cleanup/uncertainty boundaries for the resource mapping experiment."""
from pathlib import Path
import hashlib
import struct
import tempfile
import unittest
from unittest.mock import patch as mock_patch
from research_fixtures import retained_capture

from test_normal_fps_patch import NormalTransport
from test_loader_probe import FakeTransport
import normal_resource_patch as patch


class ResourceTransport(NormalTransport):
    def __init__(self, failure=None):
        super().__init__(failure)
        image = (patch.SOURCE / "XT30II_FW204_section_00600060.bin").read_bytes()
        self.put(patch.REGION, image[patch.REGION - 0x01E12000:patch.REGION + patch.REGION_SIZE - 0x01E12000])
        self.put(0x025D1CA8, image[0x025D1CA8 - 0x01E12000:0x025D1E68 - 0x01E12000])
        self.put(patch.L1_TARGET, patch.word(patch.RX))
        self.put(0x02240D84, patch.word(0x0BE77164))
        self.put(0x013E1788, patch.word(0x7FFFFFFE))
        self.put(0x02CDDE60, b"\2\7\1\0")
        self.put(0x02E94A30, b"\7")
        self.put(0x02E137E8, bytes.fromhex("ffffffffffffffff"))
        self.put(0x0177F8C0, (patch.OUT / "movie_buffers_after_stop_request_20261012T064543530968Z/autoset.bin").read_bytes())
        self.put(0x01B85AD2, b"\4")
        self.original_code = self.get(patch.REGION, patch.REGION_SIZE)

    def read_cmd(self, length):
        request = self.requests[-1]
        op, _, _, _, fn = struct.unpack_from("<5I", request)
        if fn != 5:
            return FakeTransport.read_cmd(self, length)
        self.execution_count += 1
        if self.failure == "timeout":
            self.failed_request_count = len(self.requests)
            raise TimeoutError("No complete response")
        if self.failure == "reject":
            return struct.pack("<5I", op, 1, 3, 0, fn) + request[20:36]
        action = struct.unpack("<I", self.get(patch.REPORT + 4, 4))[0]
        self.put(patch.ROOT_PTR, patch.word(patch.TABLE))
        self.put(patch.CALLBACK, patch.word(patch.NORMAL_CALLBACK))
        self.put(patch.STATE + 12, patch.word(patch.CODE))
        expected = patch.REPLACEMENT if action == 2 else patch.ORIGINAL
        replacement = patch.REPLACEMENT if action == 1 else patch.ORIGINAL
        if action:
            self.put(patch.TARGET, patch.word(replacement))
        if self.failure == "extra_write":
            self.put(patch.TARGET + 4, patch.word(0xDEADBEEF))
        self.put(patch.REPORT, struct.pack("<11I", patch.MAGIC, action,
            0x80000004 if self.failure == "native" else 2,
            expected, expected, replacement, 0, 0, int(action != 0), int(action != 0), int(action != 0)))
        return struct.pack("<5I", op, 0, 0, 0, fn) + request[20:36]


class ResourcePatchTests(unittest.TestCase):
    def run_case(self, camera, action):
        record = lambda *args, **kwargs: None
        protocol = patch.PatchProtocol(camera, record)
        arena = {"code_sha256": hashlib.sha256(camera.get(patch.CODE, 836)).hexdigest(),
                 "usb_branch": 0x0BE77164}
        with mock_patch.object(patch, 'capture', retained_capture), tempfile.TemporaryDirectory() as folder:
            patch.run_patch(protocol, arena, action, Path(folder), record)

    def test_probe_preserves_complete_section_and_owned_page(self):
        c = ResourceTransport()
        self.run_case(c, "probe")
        self.assertEqual(c.get(patch.REGION, patch.REGION_SIZE), c.original_code)
        self.assertEqual(c.get(patch.STATE, 4096), c.initial_state)
        self.assertEqual(c.get(0x013E1788, 4), patch.word(0x7FFFFFFE))
        self.assertEqual(c.execution_count, 1)

    def test_apply_then_restore_changes_exact_policy_word(self):
        c = ResourceTransport()
        self.run_case(c, "apply")
        self.assertEqual(c.get(patch.TARGET, 4), patch.word(patch.REPLACEMENT))
        self.run_case(c, "restore")
        self.assertEqual(c.get(patch.REGION, patch.REGION_SIZE), c.original_code)
        self.assertEqual(c.get(patch.STATE, 4096), c.initial_state)
        self.assertEqual(c.debug_flag, 1)

    def test_timeout_has_zero_followup_commands(self):
        c = ResourceTransport("timeout")
        with self.assertRaises(TimeoutError):
            self.run_case(c, "apply")
        self.assertEqual(len(c.requests), c.failed_request_count)
        self.assertEqual(c.execution_count, 1)

    def test_complete_rejection_restores_predispatch_controls(self):
        c = ResourceTransport("reject")
        with self.assertRaises(patch.ApplicationError):
            self.run_case(c, "apply")
        self.assertEqual(c.get(patch.STATE, 4096), c.initial_state)
        self.assertEqual(c.get(patch.CALLBACK, 4), patch.word(patch.NORMAL_CALLBACK))
        self.assertEqual(c.get(patch.ROOT_PTR, 4), patch.word(patch.TABLE))
        self.assertEqual(c.get(patch.REGION, patch.REGION_SIZE), c.original_code)

    def test_unverified_native_failure_preserves_evidence(self):
        c = ResourceTransport("native")
        with self.assertRaises(RuntimeError):
            self.run_case(c, "apply")
        self.assertNotEqual(c.get(patch.STATE + 0x100, 0xF00), c.initial_state[0x100:])
        self.assertEqual(struct.unpack_from("<I", c.requests[-1], 16)[0], 2)

    def test_extra_code_write_is_detected_and_evidence_preserved(self):
        c = ResourceTransport("extra_write")
        with self.assertRaisesRegex(RuntimeError, "complete 1 MiB"):
            self.run_case(c, "apply")
        self.assertNotEqual(c.get(patch.STATE + 0x100, 0xF00), c.initial_state[0x100:])
        self.assertEqual(c.execution_count, 1)

    def test_active_recording_prevents_staging(self):
        c = ResourceTransport()
        c.put(0x02E137EC, patch.word(0x02E137F0))
        with self.assertRaisesRegex(RuntimeError, "active"):
            self.run_case(c, "apply")
        self.assertEqual(c.execution_count, 0)
        self.assertEqual(c.get(patch.STATE, 4096), c.initial_state)

    def test_host_cannot_directly_write_policy_or_permissions(self):
        c = ResourceTransport()
        p = patch.PatchProtocol(c, lambda *args, **kwargs: None)
        for address in (patch.TARGET, patch.L1_TARGET, patch.HEAP_L2, 0x06B95000):
            with self.assertRaises(ValueError):
                p.write(address, patch.word(0))
        self.assertEqual(c.requests, [])


if __name__ == "__main__":
    unittest.main()
