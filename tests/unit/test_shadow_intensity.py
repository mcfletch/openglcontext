"""X3D's `shadowIntensity`: how dark a light's shadow is, from 0 (none) to 1 (full).

A shadowed point receives `1 - shadowIntensity` of the light it would get
unshadowed, as the passes draw it.
"""
import numpy as np
import pytest

from OpenGLContext.passes.shadowmixin import shadow_intensity
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.testing.scenes import drawn_image, scene_context


@pytest.mark.parametrize('given, expected', [(1.0, 1.0), (0.25, 0.25), (0.0, 0.0),
                                             (-1.0, 0.0), (7.0, 1.0), (float('nan'), 1.0)])
def test_the_intensity_is_held_between_none_and_full(given, expected):
    light = basenodes.DirectionalLight(shadowIntensity=given)
    assert shadow_intensity(light) == pytest.approx(expected)


def test_a_light_without_the_field_casts_full_shadows():
    assert shadow_intensity(object()) == 1.0


def _floor_beside_and_in_the_shadow(intensity):
    """The floor's brightness clear of the caster, and where its shadow falls

    Seen from above, with the sun slanting so the shadow lands beside the
    caster rather than under it.
    """
    floor = basenodes.Transform(translation=(0, -1, 0), children=[basenodes.Shape(
        geometry=basenodes.Box(size=(20, 0.1, 20)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1))))])
    caster = basenodes.Transform(translation=(0, 1, 0), children=[basenodes.Shape(
        geometry=basenodes.Box(size=(2, 0.2, 2)),
        appearance=basenodes.Appearance(material=basenodes.Material(diffuseColor=(1, 1, 1))))])
    sun = basenodes.DirectionalLight(direction=(1, -1, 0), intensity=1.0, shadows=True,
                                     shadowIntensity=intensity)
    eye = basenodes.Viewpoint(position=(0, 8, 0), orientation=(1, 0, 0, -1.5707963))
    with scene_context([eye, basenodes.NavigationInfo(headlight=False), sun, floor, caster],
                       size=(64, 64)) as context:
        for _ in range(3):
            context.OnDraw(force=1)
        image = drawn_image(context).astype(float)
    h, w = image.shape[:2]
    # About 2.5 m left of the caster, and 2 m right of it where the shadow is.
    return (image[h // 2 - 2:h // 2 + 2, 9:12].mean(),
            image[h // 2 - 2:h // 2 + 2, 48:51].mean())


def test_no_intensity_is_no_shadow_and_full_intensity_is_full_shadow(gl_context):
    lit_full, under_full = _floor_beside_and_in_the_shadow(1.0)
    lit_none, under_none = _floor_beside_and_in_the_shadow(0.0)
    assert under_full < 0.7 * lit_full
    assert under_none == pytest.approx(lit_none, rel=0.15)
    assert np.isfinite([lit_full, under_full, lit_none, under_none]).all()
