"""Stage-specific, content-addressed inputs for offline camera test doubles.

Live acquisition selection belongs to the research tools. Unit tests use this
manifest exclusively, so new evidence cannot silently change their baseline.
"""
from functools import partial
import hashlib
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def capture(profile, address, size, *, root=FIXTURES):
    manifest = json.loads((root / "manifest.json").read_text())
    if manifest["schema_version"] != 1:
        raise ValueError("Unsupported test fixture manifest")
    try:
        item = manifest["profiles"][profile]["captures"][f"{address:08x}/{size}"]
    except KeyError as error:
        raise ValueError(f"No pinned {profile} fixture for {address:#x}/{size}") from error
    path = (root / item["file"]).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ValueError("Test fixture escapes its root")
    data = path.read_bytes()
    if len(data) != size or hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError(f"Pinned test fixture identity changed: {path.name}")
    return data


cold_capture = partial(capture, "cold_jig")
retained_capture = partial(capture, "retained_rec")
