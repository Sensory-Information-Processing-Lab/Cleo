"""Tests for ephys.spiking module"""
import numpy as np

from brian2 import SpikeGeneratorGroup, ms, mm, Network
from cleo import CLSimulator
from cleo.ephys import *
from cleo.ioproc import RecordOnlyProcessor


def _spike_generator_group(z_coords_mm, indices=None, times_ms=None, **kwparams):
    N = len(z_coords_mm)
    if indices is None:
        indices = range(N)
        times_ms = np.zeros(N)
    sgg = SpikeGeneratorGroup(N, indices, times_ms * ms, **kwparams)
    for var in ["x", "y", "z"]:
        sgg.add_attribute(var)
    sgg.x = np.zeros(N) * mm
    sgg.y = np.zeros(N) * mm
    sgg.z = z_coords_mm * mm
    return sgg


def test_MUS_multiple_contacts():
    np.random.seed(1830)
    # raster of test spikes: each character is 1-ms bin
    # | || |  <- neuron 0, 0mm     contact at .25mm
    #    |||  <- neuron 1, 0.5mm   contact at .75mm
    #     ||  <- neuron 2, 1mm
    indices = [0, 0, 0, 1, 1, 2, 0, 1, 2]
    times = [0.9, 2.1, 3.5, 3.5, 4.1, 4.9, 5.1, 5.3, 5.5]
    sgg = _spike_generator_group((0, 0.5, 1), indices, times)
    net = Network(sgg)
    sim = CLSimulator(net)
    mus = MultiUnitSpiking(
        "mus",
        perfect_detection_radius=0.3 * mm,
        half_detection_radius=0.75 * mm,
        save_history=True,
    )
    probe = Probe("probe", [[0, 0, 0.25], [0, 0, 0.75]] * mm, [mus])
    sim.inject_recorder(probe, sgg)

    # remember i here is channel, no longer neuron
    i, t, y = mus.get_state()
    assert len(i) == 0
    assert len(t) == 0

    sim.run(1 * ms)  # 1 ms
    i, t, y = mus.get_state()
    assert (0 in i) and (0.9 in t)

    sim.run(1 * ms)  # 2 ms
    i, t, y = mus.get_state()
    assert len(i) == 0 and len(t) == 0

    sim.run(1 * ms)  # 3 ms
    i, t, y = mus.get_state()
    assert (0 in i) and (2.1 in t)

    sim.run(1 * ms)  # 4 ms
    i, t, y = mus.get_state()
    # should pick up 2 spikes on first and 1 or 2 on second channel
    assert 1 in i and len(i) >= 3
    assert 3.5 in t

    # skip to 6 ms
    sim.run(2 * ms)
    # sim.get_state() nested dict is what will be passed to IO processor
    i, t, y = sim.get_state()["probe"]["mus"]
    assert (0 in i) and (1 in i) and len(i) >= 7
    assert all(t_i in t.round(2) for t_i in [4.1, 4.9, 5.1, 5.3, 5.5])

    # should have picked up at least one but not all spikes outside perfect radius
    assert len(mus.i) > 12
    # each channel should have picked up not all spikes
    assert np.sum(mus.i == 0) < len(indices)
    assert np.sum(mus.i == 1) < len(indices)

    assert len(mus.i) == len(mus.t_ms)


def test_MUS_multiple_groups():
    np.random.seed(1836)
    sgg1 = _spike_generator_group((0, 0.1, 9000), period=1 * ms)  # i_probe = 4, 5
    sgg2 = _spike_generator_group((0.19, 0.2), period=0.5 * ms)  # i_probe = 6, 7
    # too far away to record at all:
    sgg3 = _spike_generator_group((9000,), period=1 * ms)
    net = Network(sgg1, sgg2, sgg3)
    sim = CLSimulator(net)
    mus = MultiUnitSpiking(
        "mus",
        perfect_detection_radius=0.1 * mm,
        half_detection_radius=0.2 * mm,
        save_history=True,
    )
    probe = Probe("probe", [[0, 0, 0], [0, 0, 0.1]] * mm, [mus])
    sim.inject_recorder(probe, sgg1, sgg2, sgg3)

    sim.run(10 * ms)
    i, t, y = mus.get_state()
    # first channel would have caught about half the spikes from sgg2
    assert 20 < np.sum(mus.i == 0) < 60
    # second channel would have caught all spikes from sgg1 and sgg2
    assert np.sum(mus.i == 1) == 60


def test_MUS_reset():
    _test_reset(MultiUnitSpiking)


def test_SortedSpiking():
    np.random.seed(1918)
    # sgg0 neurons at i_eg 0 and 1 are in range, but have no spikes
    sgg0 = _spike_generator_group((0.1, 777, 0.3), indices=[], times_ms=[])
    # raster of test spikes: each character is 1-ms bin
    #        i_ng, i_eg, distance
    # | || |  <- 0, 2, 0mm     contact at .25mm
    #    |||  <- 1, 3, 0.5mm   contact at .75mm
    # ||||||  <- 2, _, 100mm   out of range: shouldn't get detected
    #         <- 3, 4, -0.1mm  in range, but no spikes
    #     ||  <- 4, 5, 1mm
    indices = [0, 0, 0, 1, 1, 4, 0, 1, 4, 2, 2, 2, 2, 2, 2]
    times = [0.9, 2.1, 3.5, 3.5, 4.1, 4.9, 5.1, 5.3, 5.5, 0, 1, 2, 3, 4, 5]
    sgg1 = _spike_generator_group((0, 0.5, 100, -0.1, 1), indices, times)
    net = Network(sgg0, sgg1)
    sim = CLSimulator(net)
    ss = SortedSpiking(
        "ss",
        perfect_detection_radius=0.3 * mm,
        half_detection_radius=0.75 * mm,
        save_history=True,
    )
    probe = Probe("probe", [[0, 0, 0.25], [0, 0, 0.75], [0, 0, 10]] * mm, [ss])
    # injecting sgg0 before sgg1 needed to predict i_eg
    sim.inject_recorder(probe, sgg0, sgg1)

    sim.run(3 * ms)  # 3 ms
    i, t, y = sim.get_state()["probe"]["ss"]
    assert all(i == [2, 2])

    sim.run(1 * ms)  # 4 ms
    i, t, y = ss.get_state()
    assert all(i == [2, 3])

    sim.run(1 * ms)  # 5 ms
    i, t, y = ss.get_state()
    assert all(i == [3, 5])

    sim.run(1 * ms)  # 6 ms
    i, t, y = ss.get_state()
    assert all(i == [2, 3, 5])

    for i in (0, 1, 4):
        assert not i in ss.i


def _test_reset(spike_signal_class):
    sgg = _spike_generator_group([0], period=1 * ms)
    net = Network(sgg)
    sim = CLSimulator(net)
    spike_signal = spike_signal_class(
        "spikes",
        perfect_detection_radius=0.3 * mm,
        half_detection_radius=0.75 * mm,
        save_history=True,
    )
    probe = Probe("probe", [[0, 0, 0]] * mm, [spike_signal])
    sim.inject_recorder(probe, sgg)
    sim.set_io_processor(RecordOnlyProcessor(sample_period_ms=1))
    assert len(spike_signal.i) == 0
    assert len(spike_signal.t_ms) == 0
    sim.run(3.1 * ms)
    assert len(spike_signal.i) == 3
    assert len(spike_signal.t_ms) == 3
    sim.reset()
    assert len(spike_signal.i) == 0
    assert len(spike_signal.t_ms) == 0


def test_SortedSpiking_reset():
    _test_reset(SortedSpiking)
