"""Basic processor and processing block definitions"""
from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Tuple, Any
from collections import deque

import numpy as np

from cleosim.base import IOProcessor
from cleosim.processing.delays import Delay


class ProcessingBlock(ABC):
    """Abstract signal processing stage or control block."""

    delay: Delay
    """The delay object determining compute latency for the block"""
    save_history: bool
    """Whether to record :attr:`t_in_ms`, :attr:`t_out_ms`, 
    and :attr:`values` with every timestep"""
    t_in_ms: list[float]
    """The walltime the block received each input.
    Only recorded if :attr:`save_history`"""
    t_out_ms: list[float]
    """The walltime of each of the block's outputs.
    Only recorded if :attr:`save_history`"""
    values: list[Any]
    """Each of the block's outputs.
    Only recorded if :attr:`save_history`"""

    def __init__(self, **kwargs):
        """Construct a `ProcessingBlock` object.

        It's important to use `super().__init__(**kwargs)` in the base class
        to use the parent-class logic here.

        Keyword args
        ------------
        delay : Delay
            Delay object which adds to the compute time

        Raises
        ------
        TypeError
            When `delay` is not a `Delay` object.
        """
        self.delay = kwargs.get("delay", None)
        if not isinstance(self.delay, Delay):
            raise TypeError("delay must be of the Delay class")
        self.save_history = kwargs.get("save_history", False)
        if self.save_history is True:
            self.t = []
            self.out_t = []
            self.values = []

    def process(self, input: Any, in_time_ms: float, **kwargs) -> Tuple[Any, float]:
        """Compute output and output time given input and input time.

        The user should implement :func:`~_process()`, which performs the
        computation itself without regards for the delay.

        Parameters
        ----------
        input : Any
        in_time_ms : float
        **kwargs : key-value list of arguments passed to :func:`~_process()`

        Returns
        -------
        Tuple[Any, float]
            output, out time
        """
        out = self._process(input, **kwargs)
        if self.delay is not None:
            out_time_ms = in_time_ms + self.delay.compute()
        else:
            out_time_ms = in_time_ms
        if self.save_history:
            self.t.append(in_time_ms)
            self.out_t.append(out_time_ms)
            self.values.append(out)
        return (out, out_time_ms)

    @abstractmethod
    def _process(self, input: Any, **kwargs) -> Any:
        """Computes output for given input.

        This is where the user will implement the desired functionality
        of the `ProcessingBlock` without regard for latency.

        Parameters
        ----------
        input : Any
        **kwargs : optional key-value argument pairs passed from
        :func:`process`. Could be used to pass in such values as
        the IO processor's walltime or the measurement time for time-
        dependent functions.

        Returns
        -------
        Any
            output.
        """
        pass


class LatencyIOProcessor(IOProcessor):
    """IOProcessor capable of delivering stimulation some time after measurement.

    For non-serial processing,
    """

    def __init__(self, sample_period_ms: float, **kwargs):
        """
        Parameters
        ----------
        sample_period_ms : float
            Determines how frequently samples are taken from the network.

        Keyword args
        ------------
        sampling : str
            "fixed" or "when idle"; "fixed" by default

            "fixed" sampling means samples are taken on a fixed schedule,
            with no exceptions.

            "when idle" sampling means no samples are taken before the previous
            sample's output has been delivered. A sample is taken ASAP
            after an over-period computation: otherwise remains on schedule.
        processing : str
            "parallel" or "serial"; "parallel" by default

            "parallel" computes the output time by adding the delay for a sample
            onto the sample time, so if the delay is 2 ms, for example, while the
            sample period is only 1 ms, some of the processing is happening in
            parallel. Output order matches input order even if the computed
            output time for a sample is sooner than that for a previous
            sample.

            "serial" computes the output time by adding the delay for a sample
            onto the output time of the previous sample, rather than the sampling
            time. Note this may be of limited
            utility because it essentially means the *entire* round trip
            cannot be in parallel at all. More realistic is that simply
            each block or phase of computation must be serial. If anyone
            cares enough about this, it will have to be implemented in the
            future.

        Note
        ----
        Note: it doesn't make much sense to combine parallel computation
        with "when idle" sampling, because "when idle" sampling only produces
        one sample at a time to process.

        Raises
        ------
        ValueError
            For invalid `sampling` or `processing` kwargs
        """
        self.out_buffer = deque([])
        self.sample_period_ms = sample_period_ms
        self.sampling = kwargs.get("sampling", "fixed")
        if self.sampling not in ["fixed", "when idle"]:
            raise ValueError("Invalid sampling scheme:", self.sampling)
        self.processing = kwargs.get("processing", "parallel")
        if self.processing not in ["serial", "parallel"]:
            raise ValueError("Invalid processing scheme:", self.processing)

    def put_state(self, state_dict: dict, sample_time_ms):
        out, out_time_ms = self.process(state_dict, sample_time_ms)
        if self.processing == "serial" and len(self.out_buffer) > 0:
            prev_out_time_ms = self.out_buffer[-1][1]
            # add delay onto the output time of the last computation
            out_time_ms = prev_out_time_ms + out_time_ms - sample_time_ms
        self.out_buffer.append((out, out_time_ms))
        self._needs_off_schedule_sample = False

    def get_ctrl_signal(self, query_time_ms):
        if len(self.out_buffer) == 0:
            return None
        next_out_signal, next_out_time_ms = self.out_buffer[0]
        if query_time_ms >= next_out_time_ms:
            self.out_buffer.popleft()
            return next_out_signal
        else:
            return None

    def _is_currently_idle(self, query_time_ms):
        return len(self.out_buffer) == 0 or self.out_buffer[0][1] <= query_time_ms

    def is_sampling_now(self, query_time_ms):
        if self.sampling == "fixed":
            if np.isclose(query_time_ms % self.sample_period_ms, 0):
                return True
        elif self.sampling == "when idle":
            if query_time_ms % self.sample_period_ms == 0:
                if self._is_currently_idle(query_time_ms):
                    self._needs_off_schedule_sample = False
                    return True
                else:  # if not done computing
                    self._needs_off_schedule_sample = True
                    return False
            else:
                # off-schedule, only sample if the last sampling period
                # was missed (there was an overrun)
                return self._needs_off_schedule_sample and self._is_currently_idle(
                    query_time_ms
                )
        return False

    @abstractmethod
    def process(self, state_dict: dict, sample_time_ms: float) -> Tuple[dict, float]:
        """Process network state to generate output to update stimulators.

        This is the function the user must implement to define the signal processing
        pipeline.

        Parameters
        ----------
        state_dict : dict
            {`recorder_name`: `state`} dictionary from :func:`~cleosim.CLSimulator.get_state()`
        time_ms : float

        Returns
        -------
        Tuple[dict, float]
            {'stim_name': `ctrl_signal`} dictionary and output time in milliseconds.
        """
        pass


class RecordOnlyProcessor(LatencyIOProcessor):
    """Take samples without performing any control.

    Use this if all you are doing is recording."""

    def __init__(self, sample_period_ms, **kwargs):
        super().__init__(sample_period_ms, **kwargs)

    def process(self, state_dict: dict, sample_time_ms: float) -> Tuple[dict, float]:
        return ({}, sample_time_ms)