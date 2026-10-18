from __future__ import annotations

import time

import numpy as np

from trio_kit.constants import BLOCK
from trio_kit.dsp import Adsr, Biquad, Chorus, DelayLine, Lfo, Reverb, StereoDelay


def test_aggregate_dsp_block_processing_has_a_generous_runtime_guard() -> None:
    rng = np.random.default_rng(18)
    source = rng.normal(0, 0.15, (BLOCK, 2)).astype(np.float32)
    envelope = Adsr()
    envelope.gate_on(0.7)
    filter_ = Biquad()
    lfo = Lfo(rate=2, waveform="smooth_random", seed=4)
    line = DelayLine(512, channels=2)
    chorus = Chorus(seed=4)
    delay = StereoDelay(delay_seconds=0.06)
    reverb = Reverb()

    started = time.perf_counter()
    for _ in range(96):
        envelope.process(BLOCK)
        filter_.process(source)
        lfo.process(BLOCK)
        line.process(source, 256)
        chorus.process(source)
        delay.process(source)
        reverb.process(source)
    elapsed = time.perf_counter() - started

    assert elapsed < 10.0
