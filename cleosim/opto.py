from typing import Tuple

from brian2 import Synapses, Equations
from brian2.units import *
from brian2.units.allunits import meter2
import brian2.units.unitsafefunctions as usf
from brian2.core.base import BrianObjectException
import numpy as np
import matplotlib

from cleosim.utilities import wavelength_to_rgb
from cleosim.stimulators import Stimulator


# from PyRhO: Evans et al. 2016
# assuming this model is defined on "synapses" influencing a post-synaptic
# target population. rho_rel is channel density relative to standard model fit,
# allowing for heterogeneous opsin expression.
four_state = """
    dC1/dt = Gd1*O1 + Gr0*C2 - Ga1*C1 : 1 (clock-driven)
    dO1/dt = Ga1*C1 + Gb*O2 - (Gd1+Gf)*O1 : 1 (clock-driven)
    dO2/dt = Ga2*C2 + Gf*O1 - (Gd2+Gb)*O2 : 1 (clock-driven)
    C2 = 1 - C1 - O1 - O2 : 1
    # dC2/dt = Gd2*O2 - (Gr0+Ga2)*C2 : 1 (clock-driven)

    Theta = int(phi > 0*phi) : 1
    Hp = Theta * phi**p/(phi**p + phim**p) : 1
    Ga1 = k1*Hp : hertz
    Ga2 = k2*Hp : hertz
    Hq = Theta * phi**q/(phi**q + phim**q) : 1
    Gf = kf*Hq + Gf0 : hertz
    Gb = kb*Hq + Gb0 : hertz

    fphi = O1 + gamma*O2 : 1
    fv = (1 - exp(-(V_VAR_NAME_post-E)/v0)) / -2 : 1

    IOPTO_VAR_NAME_post = g0*fphi*fv*(V_VAR_NAME_post-E)*rho_rel : ampere (summed)
    rho_rel : 1
"""

# from try.projectpyrho.org's default 4-state params
ChR2_four_state = {
    "g0": 114000 * psiemens,
    "gamma": 0.00742,
    "phim": 2.33e17 / mm2 / second,  # *photon, not in Brian2
    "k1": 4.15 / ms,
    "k2": 0.868 / ms,
    "p": 0.833,
    "Gf0": 0.0373 / ms,
    "kf": 0.0581 / ms,
    "Gb0": 0.0161 / ms,
    "kb": 0.063 / ms,
    "q": 1.94,
    "Gd1": 0.105 / ms,
    "Gd2": 0.0138 / ms,
    "Gr0": 0.00033 / ms,
    "E": 0 * mV,
    "v0": 43 * mV,
    "v1": 17.1 * mV,
}

# from Foutz et al. 2012
default_blue = {
    "R0": 0.1 * mm,  # optical fiber radius
    "NAfib": 0.37,  # optical fiber numerical aperture
    "wavelength": 473 * nmeter,
    # NOTE: the following depend on wavelength and tissue properties and thus would be different for another wavelength
    "K": 0.125 / mm,  # absorbance coefficient
    "S": 7.37 / mm,  # scattering coefficient
    "ntis": 1.36,  # tissue index of refraction
}


class OptogeneticIntervention(Stimulator):
    """
    Requires neurons to have 3D spatial coordinates already assigned.
    Will add the necessary equations to the neurons for the optogenetic model.

    Optional kwparams that can be included in `inject_stimulator`:
    p_expression and rho_rel
    """

    def __init__(
        self,
        name,
        opsin_model: str,
        opsin_params: dict,
        light_model_params: dict,
        location: Tuple[float, float, float] = (0, 0, 0) * mm,
        direction: Tuple[float, float, float] = (0, 0, 1),
        start_value=0 * mwatt / mm2,
    ):
        """
        direction: (x,y,z) tuple representing direction light is pointing
        """
        super().__init__(name, start_value)
        self.opsin_model = opsin_model
        self.opsin_params = opsin_params
        self.light_model_params = light_model_params
        self.location = location
        # direction unit vector
        self.dir_uvec = (direction / np.linalg.norm(direction)).reshape((3, 1))
        self.opto_syns = {}

    def _Foutz12_transmittance(self, r, z, scatter=True, spread=True, gaussian=True):
        """Foutz et al. 2012 transmittance model: Gaussian cone with Kubelka-Munk propagation"""

        if spread:
            # divergence half-angle of cone
            theta_div = np.arcsin(
                self.light_model_params["NAfib"] / self.light_model_params["ntis"]
            )
            Rz = self.light_model_params["R0"] + z * np.tan(
                theta_div
            )  # radius as light spreads("apparent radius" from original code)
            C = (self.light_model_params["R0"] / Rz) ** 2
        else:
            Rz = self.light_model_params["R0"]  # "apparent radius"
            C = 1

        if gaussian:
            G = 1 / np.sqrt(2 * np.pi) * np.exp(-2 * (r / Rz) ** 2)
        else:
            G = 1

        def kubelka_munk(dist):
            S = self.light_model_params["S"]
            a = 1 + self.light_model_params["K"] / S
            b = np.sqrt(a ** 2 - 1)
            dist = np.sqrt(r ** 2 + z ** 2)
            return b / (a * np.sinh(b * S * dist) + b * np.cosh(b * S * dist))

        M = kubelka_munk(np.sqrt(r ** 2 + z ** 2)) if scatter else 1

        T = G * C * M
        return T

    def get_rz_for_xyz(self, x, y, z):
        """Assumes x, y, z already have units"""

        def flatten_if_needed(var):
            if len(var.shape) != 1:
                return var.flatten()
            else:
                return var

        # have to add unit back on since it's stripped by vstack
        coords = (
            np.vstack(
                [flatten_if_needed(x), flatten_if_needed(y), flatten_if_needed(z)]
            ).T
            * meter
        )
        rel_coords = coords - self.location  # relative to fiber location
        # must use brian2's dot function for matrix multiply to preserve
        # units correctly.
        zc = usf.dot(rel_coords, self.dir_uvec)  # distance along cylinder axis
        # just need length (norm) of radius vectors
        # not using np.linalg.norm because it strips units
        r = np.sqrt(np.sum((rel_coords - usf.dot(zc, self.dir_uvec.T)) ** 2, axis=1))
        r = r.reshape((-1, 1))
        return r, zc

    def connect_to_neuron_group(self, neuron_group, **kwparams):
        p_expression = kwparams.get("p_expression", 1)
        Iopto_var_name = kwparams.get("Iopto_var_name", "Iopto")
        v_var_name = kwparams.get("v_var_name", "v")
        for variable, unit in zip([v_var_name, Iopto_var_name], [volt, amp]):
            if (
                variable not in neuron_group.variables
                or neuron_group.variables[variable].unit != unit
            ):
                raise BrianObjectException(
                    (
                        f"{variable} : {unit.name} needed in the model of NeuronGroup"
                        f"{neuron_group.name} to connect OptogeneticIntervention."
                    ),
                    neuron_group,
                )
        # opsin synapse model needs modified names
        modified_opsin_model = self.opsin_model.replace(
            "IOPTO_VAR_NAME", Iopto_var_name
        ).replace("V_VAR_NAME", v_var_name)

        # fmt: off
        # Ephoton = h*c/lambda
        E_photon = (
            6.63e-34 * meter2 * kgram / second
            * 2.998e8 * meter / second
            / self.light_model_params["wavelength"]
        )
        # fmt: on

        light_model = """
            Irr = Irr0*T : watt/meter**2
            Irr0 : watt/meter**2 
            T : 1
            phi = Irr / Ephoton : 1/second/meter**2
        """

        opto_syn = Synapses(
            neuron_group,
            model=modified_opsin_model + light_model,
            namespace=self.opsin_params,
            name=f"synapses_{self.name}_{neuron_group.name}",
            method='rk2',
        )
        opto_syn.namespace['Ephoton'] = E_photon

        if p_expression == 1:
            opto_syn.connect(j="i")
        else:
            opto_syn.connect(condition="i==j", p=p_expression)
        for k, v in {"C1": 1, "O1": 0, "O2": 0}.items():
            setattr(opto_syn, k, v)
        # relative channel density
        opto_syn.rho_rel = kwparams.get("rho_rel", 1)
        # calculate transmittance coefficient for each point
        r, z = self.get_rz_for_xyz(neuron_group.x, neuron_group.y, neuron_group.z)
        T = self._Foutz12_transmittance(r, z).flatten()
        # reduce to subset expressing opsin before assigning
        T = [T[k] for k in opto_syn.i]

        opto_syn.T = T

        self.opto_syns[neuron_group.name] = opto_syn
        self.brian_objects.add(opto_syn)

    def add_self_to_plot(self, ax, axis_scale_unit):
        # show light with point field, assigning r and z coordinates
        # to all points
        xlim = ax.get_xlim()
        ylim = ax.get_ylim()
        zlim = ax.get_zlim()
        x = np.linspace(xlim[0], xlim[1], 50)
        y = np.linspace(ylim[0], ylim[1], 50)
        z = np.linspace(zlim[0], zlim[1], 50)
        x, y, z = np.meshgrid(x, y, z) * axis_scale_unit

        r, zc = self.get_rz_for_xyz(x, y, z)
        T = self._Foutz12_transmittance(r, zc)
        # filter out points with <0.001 transmittance to make plotting faster
        plot_threshold = 0.001
        idx_to_plot = T[:, 0] >= plot_threshold
        x = x.flatten()[idx_to_plot]
        y = y.flatten()[idx_to_plot]
        z = z.flatten()[idx_to_plot]
        T = T[idx_to_plot, 0]
        ax.scatter(
            x / axis_scale_unit,
            y / axis_scale_unit,
            z / axis_scale_unit,
            c=T,
            cmap=self._alpha_cmap_for_wavelength(),
            marker=",",
            edgecolors="none",
            label=self.name,
        )
        handles = ax.get_legend().legendHandles
        c = wavelength_to_rgb(self.light_model_params["wavelength"] / nmeter)
        opto_patch = matplotlib.patches.Patch(color=c, label=self.name)
        handles.append(opto_patch)
        ax.legend(handles=handles)

    def update(self, Irr0_mW_per_mm2: float):
        if Irr0_mW_per_mm2 < 0:
            raise ValueError(f"{self.name}: light intensity Irr0 must be nonnegative")
        for opto_syn in self.opto_syns.values():
            opto_syn.Irr0 = Irr0_mW_per_mm2 * mwatt / mm2

    def _alpha_cmap_for_wavelength(self):
        from matplotlib import colors

        c = wavelength_to_rgb(self.light_model_params["wavelength"] / nmeter)
        c_clear = (*c, 0)
        c_opaque = (*c, 0.3)
        return colors.LinearSegmentedColormap.from_list(
            "incr_alpha", [(0, c_clear), (1, c_opaque)]
        )