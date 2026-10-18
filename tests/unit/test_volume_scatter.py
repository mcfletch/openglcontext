"""KHR_materials_volume_scatter: light scattered beneath a surface and blurred across it.

The scattering shapes are drawn into a buffer of the light their diffuse
transmission takes in, which the PBR program reads back around each of their
fragments through the Burley profile. Light scattered many times leaves the
back lobes and returns through the buffer.
"""
import math

import numpy as np
import pytest

from OpenGLContext.passes import scatter
from OpenGLContext.passes.pbrpass import VOLUME_SCATTER_BIT, pack_material_block
from OpenGLContext.scenegraph.materialextensions import VolumeScatterMaterialExtension
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial


def test_the_samples_are_a_golden_angle_spiral_outwards():
    samples, least = scatter.scatter_samples()
    assert samples.shape == (scatter.SCATTER_SAMPLES_COUNT, 3)
    assert np.all(np.diff(samples[:, 1]) > 0)
    assert least == pytest.approx(float(samples[0, 1]))
    golden = math.pi * (3.0 - math.sqrt(5.0))
    assert samples[1, 0] - samples[0, 0] == pytest.approx(golden, abs=1e-5)
    assert np.all(samples[:, 2] > 0) and np.all(np.isfinite(samples))


def test_a_material_scatters_when_it_has_the_extension_node():
    assert not scatter.has_volume_scatter(PhysicalMaterial())
    assert scatter.has_volume_scatter(
        PhysicalMaterial(extensions=[VolumeScatterMaterialExtension()]))
    assert scatter.has_volume_scatter(PhysicalMaterial(multiscatterColor=(0.5, 0.2, 0.1)))


def test_the_block_carries_the_flag_colour_and_distance():
    material = PhysicalMaterial(multiscatterColor=(0.5, 0.25, 0.125), attenuationDistance=0.3,
                                thickness=1.0)
    buf = pack_material_block(material)
    assert buf.view(np.int32)[29] & VOLUME_SCATTER_BIT
    assert np.allclose(buf[40:43], (0.5, 0.25, 0.125))
    assert buf[39] == pytest.approx(0.3)
    plain = pack_material_block(PhysicalMaterial(attenuationDistance=0.3, thickness=1.0))
    assert not plain.view(np.int32)[29] & VOLUME_SCATTER_BIT
    assert plain[27] == pytest.approx(0.3)


def test_glTF_s_infinite_distance_is_no_absorption():
    assert pack_material_block(PhysicalMaterial(thickness=1.0))[27] == 0.0


SPHERE = b'''<X3D version="4.0"><head><component name="X_ITE" level="1"/></head><Scene>
  <Background skyColor="0 0 0"/><Viewpoint position="0 0 3"/>
  <NavigationInfo headlight="false"/>
  <DirectionalLight direction="-1 0 0" intensity="2"/>
  <Shape><Appearance><PhysicalMaterial baseColor="0.9 0.8 0.7" metallic="0" roughness="0.5">
    <DiffuseTransmissionMaterialExtension diffuseTransmission="0.8"/>
    <VolumeMaterialExtension thickness="1" attenuationDistance="0.3" attenuationColor="0.9 0.3 0.2"/>
    %s
  </PhysicalMaterial></Appearance><Sphere/></Shape>
</Scene></X3D>'''


def sphere(extension):
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = Loader.loads(SPHERE % extension, 'scatter.x3d')
    with scene_context(scene, size=(64, 64), environment={'OPENGLCONTEXT_IBL': 'off'}) as context:
        return drawn_image(context)[32].astype(int)


def test_scattered_light_moves_from_the_back_lobe_to_the_lit_side(gl_context):
    plain = sphere(b'')
    scattered = sphere(b'<VolumeScatterMaterialExtension multiscatterColor="0.8 0.4 0.3"/>')
    # The far side, lit from behind, gives up the light scattered many times.
    assert scattered[12].sum() < plain[12].sum() - 60, (plain[12], scattered[12])
    # The lit side takes it back in, blurred across the terminator.
    assert scattered[40].sum() > plain[40].sum() + 60, (plain[40], scattered[40])


def test_the_buffer_has_a_unit_no_other_sampler_uses():
    from OpenGLContext.passes import pbrpass  # noqa: PLC0415 kept with its use
    from OpenGLContext.passes.reflection import REFLECTION_UNIT  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.fogcoordinate import FOG_DEPTH_UNIT  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph.skinning import SKIN_PALETTE_UNIT  # noqa: PLC0415 kept with its use
    others = (set(pbrpass.PBR_UNITS.values()) | set(pbrpass.PBR_EXT_UNITS.values())
              | {pbrpass.LAYER_CUBE_UNIT, pbrpass.LAYER_VOLUME_UNIT, pbrpass.PROJECTOR_UNIT,
                 pbrpass.BORROWED_BRDF_UNIT, REFLECTION_UNIT, SKIN_PALETTE_UNIT, FOG_DEPTH_UNIT})
    assert scatter.SCATTER_UNIT not in others
    assert FOG_DEPTH_UNIT not in others - {FOG_DEPTH_UNIT}
