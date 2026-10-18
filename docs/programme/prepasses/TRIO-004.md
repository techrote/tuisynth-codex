# TRIO-004 implementation prepass

## Live-state reconciliation

- Issue #4 is open without owner comments or duplicate pull requests.
- Its sole listed dependency, TRIO-001, is merged and green. TRIO-003 is also merged and green
  on current `main` (`abfff9a`).
- This branch starts from that verified `main` revision.

## Design notes

- Every process API accepts `0..BLOCK` frames, validates finite inputs and carries its state
  across calls. Audio effects use stereo float32 buffers; envelopes and oscillators return
  mono float32 vectors.
- `DelayLine` separates chronological `write`, `read(delay, frames)`, and causal `process`.
  Fractional reads linearly interpolate. Feedback effects read before writing and enforce a
  delay of at least one internal block.
- `Biquad` uses SciPy's stateful `lfilter`. Parameter targets are validated at call boundaries
  and smoothed over 5 ms using fixed-size coefficient spans whose state persists if callers
  split a process request at arbitrary frame counts.
- The FDN uses eight linearly interpolated delay lines, a normalized Householder transform,
  per-line one-pole damping, and a size-derived decay coefficient. It injects stereo input
  into the network and emits two decorrelated line groups.
- Tests use deterministic NumPy input and seeded generators only; no audio devices or network
  access are required.

## Qualification notes

- The shared DSP surface lives in `trio_kit.dsp` and is re-exported from `trio_kit`.
- Continuity tests compare block-sized processing with randomized chunk partitions for every
  unit, including active Biquad smoothing, seeded LFOs and feedback effects.
- The device-free suite includes the recovered chronological delay ramp, ping-pong echo
  locations/decay, limiter-independent reverb tail decay, and a generous aggregate throughput
  bound.
