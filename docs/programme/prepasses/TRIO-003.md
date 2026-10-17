# TRIO-003 implementation prepass

## Live-state reconciliation

- Issue #3 is open without owner comments or duplicate pull requests.
- TRIO-002 is merged at `1a194e7`; all four PR checks and all four `main` push checks passed.
- This issue branch starts from that verified `main` revision.

## Design notes

- Events use immutable dataclasses and validate scalar ranges at construction. Frame offsets
  are bounded to `0..255` to match the fixed engine block.
- The bounded event queue evicts parameter updates first and then non-release work. If the
  queue is saturated entirely by release-critical events, it collapses them to one `Panic`,
  preserving the stronger guarantee that no active voice can remain stuck. This edge is
  documented in the engine contract.
- Parameter snapshots are immutable values published at block boundaries. The engine drains
  queued parameter changes once per block and renders note/instrument frame offsets by
  splitting that block into contiguous spans.
- Voice stealing retains the old voice in a short, bounded fade tail while a fresh voice
  starts, so the 5 ms/10 ms release guarantees do not depend on instrument-specific voice
  implementations. Tail capacity covers two maximum queue drains plus active voices, so an
  event burst cannot evict a fade before it is rendered.
- The master bus is stateful across internal blocks and uses the documented vectorized
  envelope equation once on each assembled 256-frame block. Any non-finite sample resets
  voice/instrument/master state and silences the whole affected internal block.
- Audio output tests use deterministic fake instruments only. `sounddevice` is imported only
  by the optional backend's `start()` method; CI never opens a real device.

## Review findings and fixes

- Preserved discrete parameter values as integers in immutable snapshots so choice/step
  semantics survive transfer to voices.
- Deferred sounddevice stream cleanup after callback failure to `close()`; stopping a stream
  from its own callback can deadlock. Startup failures stop and close any partially created
  stream before enabling the null backend.
- Confirmed the queue's saturated release-only fallback replaces individual releases with a
  single all-voices panic; the RAG contract now documents that stronger release behavior.
