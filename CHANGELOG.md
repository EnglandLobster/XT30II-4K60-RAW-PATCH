# Changelog

## v0.1.1-experimental — 2026-10-29

Fix the guided install interruption observed during the public v0.1.0 camera test. After successful FPS probe/apply, pause with Chinese and English instructions to re-select UHD29.97 / MOV H264 / LongGOP / 200Mbps and close the menu before the resource, bitrate and menu policies. Declining the confirmation or a failed FPS step stops the remaining policies. Existing setting/readback guards and all eleven payload files are unchanged.

Update interactive/manual guides and the public-download device acceptance summary. Three new checkpoint regressions bring the full offline suite to 63 tests. The new host checkpoint is verified offline; the earlier camera installation completed after the equivalent manual re-selection and documented continuation.

## v0.1.0-experimental — 2026-10-29

Initial public source and patch release. Nine core ARM artifacts match the accepted X-T30 II / 2.06 RAM version, with FPS, independent buffers, 400Mbps ceiling and full-menu label. Includes two earlier diagnostic binaries, pinned transport, local reference preparation, fresh checks, interactive/manual installation, rollback guidance and historical recording acceptance.

Public packaging and the new guided entry have offline verification; the historical payload version has camera acceptance. No new physical installation was performed for this publication. Boot autoload and permanent installation are not included.
