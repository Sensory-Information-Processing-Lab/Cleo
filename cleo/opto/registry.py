from typing import Tuple

from attrs import define, field
from brian2 import NeuronGroup, Synapses, kgram, second, meter
from brian2.units.allunits import meter2, radian

from cleo.base import CLSimulator
from cleo.coords import coords_from_ng


@define
class LightOpsinRegistry:
    """Facilitates the creation and maintenance of 'neurons' and 'synapses'
    implementing many-to-many light-opsin optogenetics"""

    sim: CLSimulator = field()

    opsins_for_ng: dict[NeuronGroup, set["Opsin"]] = field(factory=dict, init=False)

    lights_for_ng: dict[NeuronGroup, set["Light"]] = field(factory=dict, init=False)

    light_prop_syns: dict[Tuple["Light", "Opsin", NeuronGroup], Synapses] = field(
        factory=dict, init=False
    )

    light_prop_model = """
        T : 1
        Irr_post = epsilon * T * Irr0_pre : watt/meter**2 (summed)
        phi_post = Irr_post / Ephoton : 1/second/meter**2 (summed)
    """

    def connect_light_to_opsin_for_ng(
        self, light: "Light", opsin: "Opsin", ng: NeuronGroup
    ):
        light_agg_ng = opsin.light_agg_ngs[ng.name]
        epsilon = opsin.epsilon(light.light_model.wavelength)
        # fmt: off
        # Ephoton = h*c/lambda
        E_photon = (
            6.63e-34 * meter2 * kgram / second
            * 2.998e8 * meter / second
            / light.light_model.wavelength
        )
        # fmt: on

        light_prop_syn = Synapses(
            light.source_ng,
            light_agg_ng,
            model=self.light_prop_model,
            namespace={"epsilon": epsilon, "Ephoton": E_photon},
            name=f"{light.name}_prop_{opsin.name}_{ng.name}",
        )
        light_prop_syn.T = light.transmittance(coords_from_ng(ng))
        light_prop_syn.connect()
        self.sim.network.add(light_prop_syn)
        self.light_prop_syns[(light, opsin, ng)] = light_prop_syn

    def register_opsin(self, opsin: "Opsin", ng: NeuronGroup):
        """Connects lights previously injected into this neuron group to this opsin"""
        self.opsins_for_ng.get(ng, set()).add(opsin)
        prev_injct_lights = self.lights_for_ng.get(ng, set())
        for light in prev_injct_lights:
            self.connect_light_to_opsin_for_ng(light, opsin, ng)

    def register_light(self, light: "Light", ng: NeuronGroup):
        """Connects light to opsins already injected into this neuron group"""
        self.lights_for_ng.get(ng, set()).add(light)
        prev_injct_opsins = self.opsins_for_ng.get(ng, set())
        for opsin in prev_injct_opsins:
            self.connect_light_to_opsin_for_ng(light, opsin, ng)


registries: dict[CLSimulator, LightOpsinRegistry] = {}


def lor_for_sim(sim: CLSimulator) -> LightOpsinRegistry:
    """Returns the registry for the given simulator"""
    assert sim is not None
    if sim not in registries:
        registries[sim] = LightOpsinRegistry(sim)
    return registries[sim]
