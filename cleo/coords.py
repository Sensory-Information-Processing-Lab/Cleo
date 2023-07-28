"""Contains functions for assigning neuron coordinates and visualizing"""

from __future__ import annotations
from typing import Tuple

from brian2 import mm, meter, Unit
from brian2.groups.group import Group
from brian2.groups.neurongroup import NeuronGroup
from brian2.units.fundamentalunits import get_dimensions
import numpy as np

from cleo.utilities import (
    get_orth_vectors_for_V,
    modify_model_with_eqs,
    uniform_cylinder_rθz,
    xyz_from_rθz,
)


def assign_coords_grid_rect_prism(
    neuron_group: NeuronGroup,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
    shape: Tuple[int, int, int],
    unit: Unit = mm,
) -> None:
    """Assign grid coordinates to neurons in a rectangular grid

    Parameters
    ----------
    neuron_group : NeuronGroup
        The neuron group to assign coordinates to
    xlim : Tuple[float, float]
        xmin, xmax, with no unit
    ylim : Tuple[float, float]
        ymin, ymax, with no unit
    zlim : Tuple[float, float]
        zmin, zmax with no unit
    shape : Tuple[int, int, int]
        n_x, n_y, n_z tuple representing the shape of the resulting grid
    unit : Unit, optional
        Brian unit determining what scale to use for coordinates, by default mm

    Raises
    ------
    ValueError
        When the shape is incompatible with the number of neurons in the group
    """
    num_grid_elements = np.product(shape)
    if num_grid_elements != len(neuron_group):
        raise ValueError(
            f"Number of elements specified in shape ({num_grid_elements}) "
            f"does not match the number of neurons in the group ({len(neuron_group)})."
        )

    x = np.linspace(xlim[0], xlim[1], shape[0])
    y = np.linspace(ylim[0], ylim[1], shape[1])
    z = np.linspace(zlim[0], zlim[1], shape[2])

    x, y, z = np.meshgrid(x, y, z)
    assign_coords(neuron_group, x, y, z)


def assign_coords_rand_rect_prism(
    neuron_group: NeuronGroup,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
    unit: Unit = mm,
) -> None:
    """Assign random coordinates to neurons within a rectangular prism

    Parameters
    ----------
    neuron_group : NeuronGroup
        neurons to assign coordinates to
    xlim : Tuple[float, float]
        xmin, xmax without unit
    ylim : Tuple[float, float]
        ymin, ymax without unit
    zlim : Tuple[float, float]
        zmin, zmax without unit
    unit : Unit, optional
        Brian unit to specify scale implied in limits, by default mm
    """
    x = (xlim[1] - xlim[0]) * np.random.random(len(neuron_group)) + xlim[0]
    y = (ylim[1] - ylim[0]) * np.random.random(len(neuron_group)) + ylim[0]
    z = (zlim[1] - zlim[0]) * np.random.random(len(neuron_group)) + zlim[0]
    assign_coords(neuron_group, x, y, z)


def assign_coords_rand_cylinder(
    neuron_group: NeuronGroup,
    xyz_start: Tuple[float, float, float],
    xyz_end: Tuple[float, float, float],
    radius: float,
    unit: Unit = mm,
) -> None:
    """Assign random coordinates within a cylinder.

    Parameters
    ----------
    neuron_group : NeuronGroup
        neurons to assign coordinates to
    xyz_start : Tuple[float, float, float]
        starting position of cylinder without unit
    xyz_end : Tuple[float, float, float]
        ending position of cylinder without unit
    radius : float
        radius of cylinder without unit
    unit : Unit, optional
        Brian unit to scale other params, by default mm
    """
    xyz_start = np.array(xyz_start)
    xyz_end = np.array(xyz_end)
    # sample uniformly over r**2 for equal area
    rs = np.sqrt(radius**2 * np.random.random(len(neuron_group)))
    thetas = 2 * np.pi * np.random.random(len(neuron_group))
    cyl_length = np.linalg.norm(xyz_end - xyz_start)
    z_cyls = cyl_length * np.random.random(len(neuron_group))

    xs, ys, zs = xyz_from_rθz(rs, thetas, z_cyls, xyz_start, xyz_end)

    assign_coords(neuron_group, xs, ys, zs, unit)


def assign_coords_uniform_cylinder(
    neuron_group: NeuronGroup,
    xyz_start: Tuple[float, float, float],
    xyz_end: Tuple[float, float, float],
    radius: float,
    unit: Unit = mm,
) -> None:
    """Assign uniformly spaced coordinates within a cylinder.

    Parameters
    ----------
    neuron_group : NeuronGroup
        neurons to assign coordinates to
    xyz_start : Tuple[float, float, float]
        starting position of cylinder without unit
    xyz_end : Tuple[float, float, float]
        ending position of cylinder without unit
    radius : float
        radius of cylinder without unit
    unit : Unit, optional
        Brian unit to scale other params, by default mm
    """
    xyz_start = np.array(xyz_start)
    xyz_end = np.array(xyz_end)
    cyl_length = np.linalg.norm(xyz_end - xyz_start)

    rs, thetas, z_cyls = uniform_cylinder_rθz(len(neuron_group), radius, cyl_length)
    xs, ys, zs = xyz_from_rθz(rs, thetas, z_cyls, xyz_start, xyz_end)

    assign_coords(neuron_group, xs, ys, zs, unit)


def assign_xyz(
    neuron_group: NeuronGroup,
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    unit: Unit = mm,
):
    """Assign arbitrary coordinates to neuron group.

    Parameters
    ----------
    neuron_group : NeuronGroup
        neurons to be assigned coordinates
    x : np.ndarray
        x positions to assign (preferably 1D with no unit)
    y : np.ndarray
        y positions to assign (preferably 1D with no unit)
    z : np.ndarray
        z positions to assign (preferably 1D with no unit)
    unit : Unit, optional
        Brian unit determining what scale to use for coordinates, by default mm
    """
    _init_variables(neuron_group)
    neuron_group.x = np.reshape(x, (-1,)) * unit
    neuron_group.y = np.reshape(y, (-1,)) * unit
    neuron_group.z = np.reshape(z, (-1,)) * unit


def assign_coords(
    neuron_group: NeuronGroup,
    coords: np.ndarray,
    unit: Unit = mm,
):
    """Assign arbitrary coordinates to neuron group.

    Parameters
    ----------
    neuron_group : NeuronGroup
        neurons to be assigned coordinates
    x : np.ndarray
        x positions to assign (preferably 1D with no unit)
    y : np.ndarray
        y positions to assign (preferably 1D with no unit)
    z : np.ndarray
        z positions to assign (preferably 1D with no unit)
    unit : Unit, optional
        Brian unit determining what scale to use for coordinates, by default mm
    """
    _init_variables(neuron_group)
    neuron_group.x = np.reshape(coords[..., 0], (-1,)) * unit
    neuron_group.y = np.reshape(coords[..., 0], (-1,)) * unit
    neuron_group.z = np.reshape(coords[..., 0], (-1,)) * unit


def coords_from_xyz(x: Quantity, y: Quantity, z: Quantity) -> Quantity:
    """Get ...x3 coordinate array from x, y, z arrays (with units)."""
    # have to add unit back on since it's stripped by vstack
    n = x.shape[-1]
    return (
        np.concatenate(
            [
                np.reshape(x, (-1, n, 1)),
                np.reshape(y, (-1, n, 1)),
                np.reshape(z, (-1, n, 1)),
            ],
            axis=-1,
        )
        * meter
    )


def coords_from_ng(ng: NeuronGroup) -> Quantity:
    """Get nx3 coordinate array from NeuronGroup."""
    return coords_from_xyz(ng.x, ng.y, ng.z)


def _init_variables(group: Group):
    for dim_name in ["x", "y", "z"]:
        if hasattr(group, dim_name):
            setattr(group, dim_name, 0 * mm)
        else:
            if type(group) == NeuronGroup:
                modify_model_with_eqs(group, f"{dim_name}: meter")
            elif issubclass(type(group), Group):
                group.variables.add_array(
                    dim_name,
                    size=group._N,
                    dimensions=get_dimensions(meter),
                    dtype=float,
                    constant=True,
                    scalar=False,
                )
            else:
                raise NotImplementedError(
                    "Coordinate assignment only implemented for brian2.Group objects"
                )
