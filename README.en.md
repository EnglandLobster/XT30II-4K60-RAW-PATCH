# X-T30 II 4K60 / 400Mbps RAM Patch

Experimental USB/Jig RAM patch for the **Fujifilm X-T30 II, camera firmware 2.06**. Records 3840×2160 at 60000/1001 fps (59.94p), MOV / H.264, with a selectable 400Mbps option and correctly scoped menu label.

[中文](README.md) · [Installation (中文)](docs/INSTALL.md) · [Releases](https://github.com/EnglandLobster/xt30ii-4k60/releases)

A continuous 128.128-second, 7,680-frame recording measured about 406.9Mbps video bitrate and passed video/audio decoding. Independent buffer allocation fixes block tearing in the initial resource configuration. The nine core ARM binaries match the accepted research artifacts byte for byte.

This release is **RAM-only**. It requires a computer on each fresh installation. Power-off and the tested automatic power-off/wake cycle remove the feature. Disable automatic power-off before installation. Boot autoload and permanent firmware flashing are unfinished research and are not included.

## Setup

Use Python 3.11+ and system libusb. Hardware acceptance was performed on macOS; Linux/Windows live installation has not been validated. Obtain the exact official X-T30 II **2.04 reference DAT** yourself; its SHA256 is checked. This file supplies offline reference code only: **do not downgrade or flash it to the 2.06 camera**.

```sh
git clone https://github.com/EnglandLobster/xt30ii-4k60.git
cd xt30ii-4k60
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
python tools/prepare.py /path/to/XT30II_FW204.DAT
python tools/check.py
```

These commands never access USB. Read the detailed installation guide before running:

```sh
python tools/install.py --execute
```

The interactive installer asks for physical confirmations, verifies a fresh cold Jig baseline, runs the accepted private-memory probe, installs the label/lifecycle hook, retires the old USB transport during the REC transition, verifies normal live view and retained debug, then probes/applies the four movie policies in order. All guards and exact readbacks remain enabled. Set the camera initially to UHD29.97, MOV/H264 LongGOP, 200Mbps; keep it idle with menus closed until all policies are installed.

After installation select UHD59.94 / MOV H264 / 400Mbps in the full movie menu. Record and check a short original clip before relying on the setup. LCD preview stutter was observed during recording; two inspected original clips had continuous timestamps, no exact duplicate frames and no decode errors. Extended thermal endurance remains untested.

## Restore stock runtime

Stop recording, wait for card activity to finish, disconnect USB, power off, remove and reinsert the battery, then boot normally. Re-select stock-supported movie settings if a menu preference persists. Never reuse an old installation after a restart, sleep/wake or uncertain transport result.

## Development and license

[Development](docs/DEVELOPMENT.md) covers building, hashes and offline tests. The packaging entry points have been tested offline; no new camera installation was performed for this publication. Historical camera acceptance is documented in [validation](docs/VALIDATION.md).

MIT for original code. Vendored fffw USB transport retains its original MIT license and pinned revision; see [THIRD_PARTY.md](THIRD_PARTY.md). Official firmware, decoded firmware code, private RAM captures and recordings are excluded. Reference files are reconstructed locally and never count as fresh device evidence.
