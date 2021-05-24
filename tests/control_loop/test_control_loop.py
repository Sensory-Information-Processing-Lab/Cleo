"""Tests for clocsim/control_loop/__init__.py"""
from typing import Any, Tuple

import pytest

from clocsim.control_loop import DelayControlLoop, LoopComponent
from clocsim.control_loop.delays import ConstantDelay, Delay


class MyLoopComponent(LoopComponent):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)

    def _process(self, input: Any, **kwargs) -> Any:
        measurement_time = kwargs["measurement_time"]
        return input + measurement_time


def test_LoopComponent():
    const_delay = 5
    my_loop_component = MyLoopComponent(
        delay=ConstantDelay(const_delay), save_history=True
    )

    # blank history to start
    assert len(my_loop_component.t) == 0
    assert len(my_loop_component.out_t) == 0
    assert len(my_loop_component.values) == 0

    meas_time = [1, 8]
    in_time = [2, 9]
    inputs = [42, -1]
    outputs = [a + b for a, b in zip(inputs, meas_time)]
    out_times = [t + const_delay for t in in_time]

    for i in [0, 1]:
        out, out_time = my_loop_component.process(
            inputs[i],
            in_time_ms=in_time[i],
            measurement_time=meas_time[i],
        )
        # process with extra arg
        assert out == outputs[i]
        # delay
        assert out_time == out_times[i]
        # save history
        assert len(my_loop_component.t) == i + 1
        assert len(my_loop_component.out_t) == i + 1
        assert len(my_loop_component.values) == i + 1


class MyDelayCL(DelayControlLoop):
    def __init__(self, sampling_period_ms, **kwargs):
        super().__init__(sampling_period_ms, **kwargs)
        self.delay = 1.199
        self.component = MyLoopComponent(delay=ConstantDelay(self.delay))

    def compute_ctrl_signal(
        self, state_dict: dict, sample_time_ms: float
    ) -> Tuple[dict, float]:
        input = state_dict["in"]
        out, out_t = self.component.process(
            input, sample_time_ms, measurement_time=sample_time_ms
        )
        return {"out": out}, out_t


def _test_DelayControlLoop(myDCL, t, sampling, inputs, outputs):
    for i in range(len(t)):
        assert myDCL.is_sampling_now(t[i]) == sampling[i]
        if myDCL.is_sampling_now(t[i]):
            myDCL.put_state({"in": inputs[i]}, t[i])
        expected_out = [out if out is None else {"out": out} for out in outputs]
        assert myDCL.get_ctrl_signal(t[i]) == expected_out[i]


def test_DelayControlLoop_fixed_serial():
    myDCL = MyDelayCL(1, sampling="fixed", processing="serial")
    t = [0, 1, 1.2, 1.3, 2, 2.3, 2.4]
    sampling = [True, True, False, False, True, False, False]
    inputs = [42, 66, -1, -1, 1847, -1, -1]
    outputs = [None, None, 42, None, None, None, 67]  # input + measurement_time
    _test_DelayControlLoop(myDCL, t, sampling, inputs, outputs)


def test_DelayControlLoop_fixed_parallel():
    myDCL = MyDelayCL(1, sampling="fixed", processing="parallel")
    t = [0, 1, 1.2, 1.3, 2, 2.3, 2.4]
    sampling = [True, True, False, False, True, False, False]
    inputs = [42, 66, -1, -1, 1847, -1, -1]
    outputs = [None, None, 42, None, None, 67, None]  # input + measurement_time
    _test_DelayControlLoop(myDCL, t, sampling, inputs, outputs)


def test_DelayControlLoop_wait_serial():
    myDCL = MyDelayCL(1, sampling="wait for computation", processing="serial")
    t = [0, 1, 1.2, 1.3, 2, 2.3, 2.4]
    sampling = [True, False, True, False, False, False, True]
    inputs = [42, -1, 66, -1, -1, -1, 1847]
    outputs = [None, None, 42, None, None, None, 67.2]  # input + measurement_time
    _test_DelayControlLoop(myDCL, t, sampling, inputs, outputs)


def test_DelayControlLoop_wait_parallel():
    assert "done" == True
    myDCL = MyDelayCL(1, sampling="wait for computation", processing="serial")
    t = [0, 1, 1.2, 1.3, 2, 2.3, 2.4]
    sampling = [True, False, True, False, False, False, True]
    inputs = [42, -1, 66, -1, -1, -1, 1847]
    outputs = [None, None, 42, None, None, None, 67.2]  # input + measurement_time
    _test_DelayControlLoop(myDCL, t, sampling, inputs, outputs)
