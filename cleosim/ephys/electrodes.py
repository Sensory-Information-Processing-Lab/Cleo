from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterable
from typing import Any, Tuple

import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d.axes3d import Axes3D
from numpy.core import numeric
import numpy.typing as npt
from brian2 import NeuronGroup, mm, Unit

from cleosim.base import Recorder


class Signal(ABC):
    name: str
    brian_objects: set
    electrode_group: ElectrodeGroup = None
    _coords: npt.NDArray

    def __init__(self, name: str) -> None:
        self.name = name
        self.brian_objects = set()

    def init_for_electrode_group(self, eg: ElectrodeGroup):
        if self.electrode_group is not None and self.electrode_group is not eg:
            raise ValueError(f"Signal {self.name} has already been initialized "
                             f"for ElectrodeGroup {self.electrode_group.name} "
                             f"and cannot be used with another.")
        self.electrode_group = eg
        self._coords = eg.coords

    @abstractmethod
    def connect_to_neuron_group(self, neuron_group: NeuronGroup, **kwparams):
        pass

    @abstractmethod
    def get_state(self) -> Any:
        pass


class ElectrodeGroup(Recorder):
    coords: npt.NDArray
    signals: list[Signal] = []
    n: int

    def __init__(
        self, name: str, coords: npt.ArrayLike, signals: Iterable[Signal] = []
    ):
        super().__init__(name)
        self.coords = np.array(coords).reshape((-1, 3))
        if len(self.coords.shape) != 2 or self.coords.shape[1] != 3:
            raise ValueError(
                "coords must be an n by 3 array with x, y, and z coordinates"
                "for n contact locations."
            )
        self.n = len(self.coords)
        for signal in signals:
            self.add_signal(signal)

    def add_signal(self, signal: Signal):
        signal.init_for_electrode_group(self)
        self.signals.append(signal)

    def connect_to_neuron_group(self, neuron_group: NeuronGroup, **kwparams):
        for signal in self.signals:
            signal.connect_to_neuron_group(neuron_group, **kwparams)
            self.brian_objects.update(signal.brian_objects)

    def get_state(self):
        state_dict = {}
        for signal in self.signals:
            state_dict[signal.name] = signal.get_state()
        return state_dict

    def add_self_to_plot(self, ax: Axes3D, axis_scale_unit: Unit):
        ax.scatter(
            self.coords[:, 0] / axis_scale_unit,
            self.coords[:, 1] / axis_scale_unit,
            self.coords[:, 2] / axis_scale_unit,
            marker="x",
            s=40,
            color="gray",
            label=self.name,
            depthshade=False,
        )
        ax.legend()


def get_1D_probe_coords(
    length: float * Unit,
    channel_count: int,
    base_location: Tuple[float, float, float] * Unit = (0, 0, 0) * mm,
    direction: Tuple[float, float, float] * Unit = (0, 0, 1),
) -> npt.NDArray:
    dir_uvec = direction / np.linalg.norm(direction)
    tip_location = base_location + length * dir_uvec
    return np.linspace(base_location, tip_location, channel_count)
