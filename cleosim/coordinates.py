from warnings import warn
from typing import Tuple

from brian2 import mm, meter
import numpy as np

from .utilities import modify_model_with_eqs


def assign_coords_grid_rect_prism(
    neuron_group,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
    shape: Tuple[int, int, int],
    unit=mm,
):
    _init_variables(neuron_group)
    if shape is None:
        raise ValueError("xyz_grid_shape argument is required for grid distribution.")
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

    neuron_group.x = x.flatten() * unit
    neuron_group.y = y.flatten() * unit
    neuron_group.z = z.flatten() * unit


def assign_coords_rand_rect_prism(
    neuron_group,
    xlim: Tuple[float, float],
    ylim: Tuple[float, float],
    zlim: Tuple[float, float],
    unit=mm,
):
    _init_variables(neuron_group)
    x = (xlim[1] - xlim[0]) * np.random.random(len(neuron_group)) + xlim[0]
    y = (ylim[1] - ylim[0]) * np.random.random(len(neuron_group)) + ylim[0]
    z = (zlim[1] - zlim[0]) * np.random.random(len(neuron_group)) + zlim[0]

    neuron_group.x = x.flatten() * unit
    neuron_group.y = y.flatten() * unit
    neuron_group.z = z.flatten() * unit


def assign_coords_rand_cylinder(neuron_group, xyz_start, xyz_end, radius, unit=mm):
    _init_variables(neuron_group)
    xyz_start = np.array(xyz_start)
    xyz_end = np.array(xyz_end)
    rs = radius * np.random.random(len(neuron_group))
    thetas = 2 * np.pi * np.random.random(len(neuron_group))
    cyl_length = np.linalg.norm(xyz_end - xyz_start)
    z_cyls = cyl_length * np.random.random(len(neuron_group))

    c = np.reshape(
        (xyz_end - xyz_start) / cyl_length, (-1, 1)
    )  # unit vector in direction of cylinder
    from scipy import linalg

    q, r = linalg.qr(
        np.hstack([c, c, c])
    )  # get two vectors orthogonal to c from QR decomp
    r1 = np.reshape(q[:, 1], (1, 3))
    r2 = np.reshape(q[:, 2], (1, 3))

    def r_unit_vecs(thetas):
        r1s = np.repeat(r1, len(thetas), 0)
        r2s = np.repeat(r2, len(thetas), 0)
        cosines = np.reshape(np.cos(thetas), (len(thetas), 1))
        sines = np.reshape(np.sin(thetas), (len(thetas), 1))
        return r1s * cosines + r2s * sines

    rs = np.reshape(rs, (len(rs), 1))
    points = np.reshape(xyz_start, (1, 3)) + (c * z_cyls).T + rs * r_unit_vecs(thetas)

    neuron_group.x = points[:, 0] * unit
    neuron_group.y = points[:, 1] * unit
    neuron_group.z = points[:, 2] * unit


def plot_neuron_positions(
    *neuron_groups,
    xlim=None,
    ylim=None,
    zlim=None,
    color=None,
    axis_scale_unit=mm,
    opto=None,
    invert_z=True,
):
    try:
        from matplotlib import pyplot as plt
        from mpl_toolkits.mplot3d import Axes3D
    except ImportError:
        raise ImportError(
            "matplotlib and mpl_toolkits modules required for this feature."
        )
    for ng in neuron_groups:
        for dim in ["x", "y", "z"]:
            if not hasattr(ng, dim):
                raise ValueError(f"{ng.name} does not have dimension {dim} defined.")

    fig = plt.figure()
    ax = fig.add_subplot(111, projection="3d")
    for ng in neuron_groups:
        if color is not None:
            ax.scatter(
                ng.x / axis_scale_unit,
                ng.y / axis_scale_unit,
                ng.z / axis_scale_unit,
                color=color,
                label=ng.name,
            )
        else:
            ax.scatter(
                ng.x / axis_scale_unit, ng.y / axis_scale_unit, ng.z / axis_scale_unit
            )
        ax.set_xlabel(f"x ({axis_scale_unit._dispname})")
        ax.set_ylabel(f"y ({axis_scale_unit._dispname})")
        ax.set_zlabel(f"z ({axis_scale_unit._dispname})")
    if xlim is not None:
        ax.set_xlim(xlim)
    if ylim is not None:
        ax.set_ylim(ylim)
    if zlim is None:
        zlim = ax.get_zlim()
    if invert_z:
        ax.set_zlim(zlim[1], zlim[0])
    else:
        ax.set_zlim(zlim)

    ax.legend()

    if opto is not None:
        opto.add_self_to_plot(ax, axis_scale_unit)

    # return fig


def _init_variables(neuron_group):
    for dim in ["x", "y", "z"]:
        if hasattr(neuron_group, dim):
            setattr(neuron_group, dim, 0 * mm)
        else:
            modify_model_with_eqs(neuron_group, f"{dim}: meter")