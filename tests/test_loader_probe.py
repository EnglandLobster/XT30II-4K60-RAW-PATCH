"""Failure-path checks for the single-shot probe, with no USB dependency."""
import importlib.util
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest.mock import patch as mock_patch

from research_fixtures import cold_capture

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import try_loader_probe as probe


class FakeTransport:
    def __init__(self, failure=None):
        self.memory, self.requests = {}, []
        self.failure = failure
        self.debug_flag = 0
        self.execution_count = 0
        self.failed_request_count = None
        self.table = cold_capture(probe.TABLE, 396)
        self.l2 = cold_capture(probe.L2, 1024)
        self.original_page = bytes(range(256)) * 16
        for address, data in (
            (probe.ROOT_PTR, struct.pack("<II", probe.TABLE, 0x00E201EC)),
            (probe.TABLE, self.table), (probe.L2, self.l2),
            (probe.L1 + 0x6B * 4, struct.pack("<I", probe.L2 | 1)),
            (probe.SCRATCH, self.original_page), (0x01B6A020, b"\x07"),
            (0x01722B84, b"\x01"), (0x01780590, bytes(12)),
        ):
            self.put(address, data)

    def put(self, address, data):
        self.memory.update({address + i: value for i, value in enumerate(data)})

    def get(self, address, size):
        return bytes(self.memory.get(address + i, 0) for i in range(size))

    def write_cmd(self, request):
        self.requests.append(request)

    def read_cmd(self, _):
        request = self.requests[-1]
        op, _, _, _, fn = struct.unpack_from("<5I", request)
        params = request[20:36]
        _, _, address, size = struct.unpack("<4I", params)
        data = b""
        if op == 0x1A0002:
            if fn == 2:
                data = bytes([self.debug_flag])
            else:
                self.debug_flag = request[36]
        elif fn == 2:
            data = self.get(address, size)
        elif fn == 3:
            self.put(address, request[36:])
        elif fn == 5:
            self.execution_count += 1
            if self.failure == "timeout":
                self.failed_request_count = len(self.requests)
                raise TimeoutError("simulated transport uncertainty")
            if self.failure == "reject":
                return struct.pack("<5I", op, 1, 3, 0, fn) + params
            self.put(probe.ROOT_PTR, struct.pack("<I", probe.TABLE))
            self.put(probe.CALLBACK, bytes(4))
            self.put(probe.SCRATCH + 0x180, struct.pack("<I", 0x50524F42))
            if self.failure == "permission":
                self.put(probe.PTE, struct.pack("<I", 0x06B955B6))
        return struct.pack("<5I", op, 0, 0, 0, fn) + params + data


@mock_patch.object(probe, "capture", cold_capture)
class LoaderProbeTests(unittest.TestCase):
    def run_case(self, camera):
        events = []
        protocol = probe.GuardedProtocol(camera, lambda event, **kw: events.append((event, kw)))
        return events, protocol

    def test_success_restores_every_owned_byte(self):
        camera = FakeTransport()
        events, protocol = self.run_case(camera)
        with tempfile.TemporaryDirectory() as folder:
            result = probe.run_probe(protocol, Path(folder),
                lambda event, **kw: events.append((event, kw)), camera.table, probe.build_page(camera.table))
        self.assertTrue(result)
        self.assertEqual(camera.execution_count, 1)
        self.assertEqual(camera.get(probe.SCRATCH, 4096), camera.original_page)
        self.assertEqual(camera.get(probe.ROOT_PTR, 4), struct.pack("<I", probe.TABLE))
        self.assertEqual(camera.get(probe.CALLBACK, 4), bytes(4))
        self.assertEqual(camera.get(probe.L2, 1024), camera.l2)
        self.assertEqual(camera.debug_flag, 0)

    def test_timeout_forbids_cleanup_commands_and_retry(self):
        camera = FakeTransport("timeout")
        events, protocol = self.run_case(camera)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(TimeoutError):
            probe.run_probe(protocol, Path(folder), lambda event, **kw: events.append((event, kw)),
                            camera.table, probe.build_page(camera.table))
        self.assertEqual(camera.execution_count, 1)
        self.assertEqual(len(camera.requests), camera.failed_request_count)
        self.assertFalse(protocol.healthy)
        self.assertIn("transport_uncertain", [e[0] for e in events])

    def test_complete_rejection_restores_host_controls(self):
        camera = FakeTransport("reject")
        events, protocol = self.run_case(camera)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(probe.ApplicationError):
            probe.run_probe(protocol, Path(folder), lambda event, **kw: events.append((event, kw)),
                            camera.table, probe.build_page(camera.table))
        self.assertEqual(camera.execution_count, 1)
        self.assertEqual(camera.get(probe.ROOT_PTR, 4), struct.pack("<I", probe.TABLE))
        self.assertEqual(camera.get(probe.CALLBACK, 4), bytes(4))
        self.assertEqual(camera.get(probe.SCRATCH, 4096), camera.original_page)
        self.assertEqual(camera.debug_flag, 0)

    def test_permission_mismatch_does_not_execute_again(self):
        camera = FakeTransport("permission")
        events, protocol = self.run_case(camera)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(RuntimeError):
            probe.run_probe(protocol, Path(folder), lambda event, **kw: events.append((event, kw)),
                            camera.table, probe.build_page(camera.table))
        self.assertEqual(camera.execution_count, 1)
        self.assertIn("permission_restore_unconfirmed", [e[0] for e in events])

    def test_preexisting_logging_blocks_staging(self):
        camera = FakeTransport()
        camera.put(0x01780590, b"\x01")
        events, protocol = self.run_case(camera)
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(RuntimeError):
            probe.run_probe(protocol, Path(folder), lambda event, **kw: events.append((event, kw)),
                            camera.table, probe.build_page(camera.table))
        self.assertEqual(camera.execution_count, 0)
        self.assertEqual(camera.get(probe.SCRATCH, 4096), camera.original_page)
        self.assertEqual(camera.debug_flag, 0)

    def test_host_cannot_write_page_table(self):
        camera = FakeTransport()
        _, protocol = self.run_case(camera)
        with self.assertRaises(ValueError):
            protocol.write(probe.PTE, struct.pack("<I", 0x06B955B6))
        self.assertEqual(camera.requests, [])


if __name__ == "__main__":
    unittest.main()
