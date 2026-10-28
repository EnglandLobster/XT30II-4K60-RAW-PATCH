# Contributing

Start with the supported X-T30 II / 2.06 boundary and [development guide](docs/DEVELOPMENT.md). Report the release, camera firmware, host OS, initial movie settings, last completed stage and exact error. Redact usernames, USB serials and personal paths; do not upload original firmware, RAM dumps or private media.

Run offline tests with your own exact reference DAT. Preserve the accepted payload hashes; keep generated files outside Git. Proposed changes need a clear failure mechanism, bounded operations, meaningful failure tests and separate offline/build/device validation. Never weaken identity, ownership, transport retirement or readback guards to make another camera pass.

Changes to other firmware, persistent installation, startup hooks or recovery are separate work requiring new acceptance. Do not put experimental persistent-write commands in the default installation path.
