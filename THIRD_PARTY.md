# Third-party provenance

Original project code and documentation: Copyright (c) 2026 EnglandLobster, MIT.

Vendored USB transport: [tiredboffin/fffw](https://github.com/tiredboffin/fffw), revision `bedc091e0b54a1a34aaf6929dd08e1db36d13b08`. Only `ff80/fftlib.py` and `ff80/60-fujig.rules` are included, unmodified, with the original [MIT license](vendor/fffw/LICENSE.md). Machine-readable provenance: [metadata/third-party.json](metadata/third-party.json).

Python dependencies are separately installed with pinned versions in `requirements.txt`: Unicorn 2.1.4 (BSD; consult its distribution for the licenses of bundled components), python-libusb1 3.4.0 (LGPL-2.1-or-later), and the system libusb library. These dependencies are not vendored in release archives.

The Fujifilm DAT and decoded firmware belong to their respective owners. They are not relicensed or distributed here. Firmware reference recipes record offsets, hashes and a small verified address relocation; users supply their own exact official file. The open-source MIT grant applies to this project's original code, not to reconstructed original firmware.

No GPL-licensed third-party camera tools are copied into this repository. Other tools and disassembly workspaces used during private research are excluded.
