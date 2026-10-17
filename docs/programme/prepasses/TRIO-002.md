# TRIO-002 implementation prepass

## Live-state reconciliation

- Issue #2 was open without owner comments.
- Its dependency, TRIO-001, was merged to `main`; the merge commit's four CI jobs passed.
- No duplicate open pull request existed when implementation resumed.

## Contract decisions

- The contract named linear, logarithmic, and exponential parameter curves without defining
  the exponential shape. The implementation uses a normalized `expm1` curve and documents
  the exact forward and inverse equations in `docs/rag/02-AUDIO-ENGINE-CONTRACT.md`.
- Recognized parameter values, including non-finite JSON constants, reach `ParamRegistry`
  validation so errors identify their parameter key. Non-finite values in extras and other
  structural fields remain `PresetError`s.
- A user file with a factory preset's id does not shadow it on its own. An explicit
  `trio-preset-overrides/1` index records successful user saves over factory entries.
- Create-only writes use a same-directory flushed temporary file and an atomic no-clobber
  link; overwrite writes use `os.replace`. Both paths are device-free and platform-tested.
- An explicit data directory is a shared root partitioned by instrument id. Default paths
  follow Windows `APPDATA` or POSIX `XDG_DATA_HOME` conventions.

## Verification scope

The required cases are covered by device-free tests for invalid specifications and values,
curve mapping and morph boundaries, preset schema and hostile input, package factory loading,
factory shadowing, rename/delete, atomic writes, and platform user-data paths. CI supplies
the Python 3.11/3.14 Linux/Windows matrix and clean wheel checks.
