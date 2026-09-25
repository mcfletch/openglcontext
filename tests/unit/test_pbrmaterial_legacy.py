"""A PBR material drawn by the fixed-function pipeline.

A glTF model's materials are ``PBRMaterial`` nodes. The compatibility profile's
pass lights them with ``glMaterial`` from their factors: the base colour as the
diffuse colour, metalness and roughness as the highlight, and the emissive
colour as the emission.
"""
import numpy as np
import pytest
from OpenGL import GL

from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial


def _state(parameter):
    return np.ravel(np.asarray(GL.glGetMaterialfv(GL.GL_FRONT, parameter), 'f'))


class _Mode:
    """What ``render`` is handed by an ``Appearance`` in the legacy pass."""


@pytest.mark.usefixtures('gl_context_compat')
def test_the_base_colour_is_the_diffuse_colour():
    alpha = PBRMaterial(baseColor=(0.8, 0.4, 0.2), metallic=0.0).render(mode=_Mode())
    assert alpha == pytest.approx(1.0)
    assert np.allclose(_state(GL.GL_DIFFUSE), (0.8, 0.4, 0.2, 1.0))


@pytest.mark.usefixtures('gl_context_compat')
def test_the_alpha_is_what_the_transparency_leaves():
    alpha = PBRMaterial(baseColor=(1, 1, 1), transparency=0.25).render(mode=_Mode())
    assert alpha == pytest.approx(0.75)
    assert _state(GL.GL_DIFFUSE)[3] == pytest.approx(0.75)


@pytest.mark.usefixtures('gl_context_compat')
def test_a_metal_takes_its_highlight_from_its_colour():
    PBRMaterial(baseColor=(0.9, 0.6, 0.2), metallic=1.0, roughness=0.2).render(mode=_Mode())
    specular = _state(GL.GL_SPECULAR)[:3]
    assert np.allclose(specular / specular.max(), np.array((0.9, 0.6, 0.2)) / 0.9)
    assert np.all(_state(GL.GL_DIFFUSE)[:3] < 0.3)


@pytest.mark.usefixtures('gl_context_compat')
def test_a_smoother_surface_has_a_tighter_highlight():
    PBRMaterial(roughness=0.9).render(mode=_Mode())
    rough = float(_state(GL.GL_SHININESS)[0])
    PBRMaterial(roughness=0.1).render(mode=_Mode())
    smooth = float(_state(GL.GL_SHININESS)[0])
    assert smooth > rough
    assert 0.0 <= rough and smooth <= 128.0


@pytest.mark.usefixtures('gl_context_compat')
def test_the_emission_is_the_emissive_colour_at_its_strength():
    PBRMaterial(emissiveColor=(0.5, 0.25, 0.0), emissiveStrength=2.0).render(mode=_Mode())
    assert np.allclose(_state(GL.GL_EMISSION)[:3], (1.0, 0.5, 0.0))


@pytest.mark.usefixtures('gl_context_compat')
def test_an_unlit_material_shows_its_base_colour_whatever_the_light():
    PBRMaterial(baseColor=(0.2, 0.7, 0.3), unlit=True).render(mode=_Mode())
    assert np.allclose(_state(GL.GL_EMISSION)[:3], (0.2, 0.7, 0.3))
    assert np.allclose(_state(GL.GL_DIFFUSE)[:3], 0.0)


@pytest.mark.usefixtures('gl_context_compat')
def test_an_invisible_material_draws_nothing():
    assert PBRMaterial(transparency=1.0).render(mode=_Mode()) == 0.0
