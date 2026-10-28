"""Fault-injection checks for the temporary callback experiment, never USB."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "src/try_native_rec_callback.py"
spec = importlib.util.spec_from_file_location("native_rec", SOURCE)
native = importlib.util.module_from_spec(spec)
spec.loader.exec_module(native)


class Device:
    def getVendorID(self): return 0x04cb
    def getProductID(self): return 0xff80
    def open(self): return self
    def claimInterface(self, number): return contextlib.nullcontext()
    def close(self): pass


class Context:
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def getDeviceList(self, **kwargs): return [Device()]


class Transport:
    max_pkt_size = 256
    def __init__(self, outcome):
        self.outcome, self.debug, self.callback = outcome, 0, 0
        self.actions = []
    def open_session(self): self.actions.append("open")
    def ping(self): return b"\x01\x00"
    def close_session(self): self.actions.append("close")
    def write_cmd(self, request): self.request = request
    def read_cmd(self, length):
        r = self.request
        op, _, _, _, fn = struct.unpack_from("<5I", r)
        params = r[20:36]
        address, size = struct.unpack_from("<2I", params, 8)
        data = b""
        if op == 0x1a0002:
            if (address, size) != (0xf7, 1): raise AssertionError("Unexpected config access")
            if fn == 2: data = bytes([self.debug])
            elif fn == 3:
                self.debug = r[36]
                self.actions.append(("debug", self.debug))
            else: raise AssertionError("Unexpected config operation")
        elif op == 0x200001 and fn == 2:
            if (address, size) == (0x01780590, 12): data = struct.pack("<3I", 0, 0, self.callback)
            elif (address, size) == (0x01722bb0, 4): data = struct.pack("<I", native.SINK)
            elif (address, size) == (0x01b6a020, 1): data = b"\x07"
            elif (address, size) == (native.CALLBACK, 4): data = struct.pack("<I", self.callback)
            else: raise AssertionError("Unexpected RAM read")
        elif op == 0x200001 and fn == 3:
            if (address, size) != (native.CALLBACK, 4): raise AssertionError("Unexpected RAM write")
            self.callback = struct.unpack_from("<I", r, 36)[0]
            self.actions.append(("callback", self.callback))
        elif op == 0x200001 and fn == 5:
            if r[36:] != b"MODE REC\n": raise AssertionError("Unexpected mode command")
            self.actions.append("mode")
            if self.outcome == "timeout": raise TimeoutError("injected transport uncertainty")
            if self.outcome == "rejected": return struct.pack("<5I", op, 1, 3, 0, fn) + params
        else: raise AssertionError("Unexpected operation")
        return struct.pack("<5I", op, 0, 0, 0, fn) + params + data


class CallbackLifecycleTests(unittest.TestCase):
    def run_case(self, outcome):
        transport = Transport(outcome)
        modules = {"usb1": types.SimpleNamespace(USBContext=Context),
                   "fftlib": types.SimpleNamespace(ftl=lambda handle: transport)}
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(sys.modules, modules), patch.object(native, "OUT", Path(directory)), \
                 patch.object(native, "preflight", return_value=[]), \
                 patch.object(sys, "argv", ["test", "--execute"]), contextlib.redirect_stdout(io.StringIO()):
                result = native.main()
            report = json.loads(next(Path(directory).glob("*.json")).read_text())
        return result, report, transport

    def test_success_restores_both_values_and_closes_same_session(self):
        result, report, transport = self.run_case("success")
        self.assertEqual(result, 0)
        self.assertEqual(transport.actions, ["open", ("debug", 1), ("callback", native.PARSER),
                                             "mode", ("callback", 0), ("debug", 0), "close"])
        self.assertFalse(report["callback_restore_unconfirmed"])
        self.assertFalse(report["debug_restore_unconfirmed"])

    def test_complete_application_rejection_is_cleaned_up_without_retry(self):
        result, report, transport = self.run_case("rejected")
        self.assertEqual(result, 1)
        self.assertEqual(transport.actions.count("mode"), 1)
        self.assertEqual(transport.actions[-3:], [("callback", 0), ("debug", 0), "close"])
        self.assertFalse(report["callback_restore_unconfirmed"])

    def test_transport_timeout_stops_commands_and_reports_unconfirmed_restore(self):
        result, report, transport = self.run_case("timeout")
        self.assertEqual(result, 1)
        self.assertEqual(transport.actions[-1], "mode")
        self.assertTrue(report["callback_restore_unconfirmed"])
        self.assertTrue(report["debug_restore_unconfirmed"])


if __name__ == "__main__": unittest.main()
