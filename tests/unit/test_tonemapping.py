"""Tone curves, exposure and colour space: the arithmetic and the choice (no GL)

The expected values are worked from the published constants: Narkowicz's
ACES fit, Hill's fit and matrices, and the Khronos PBR Neutral curve.
"""
import numpy as np
import pytest

from OpenGLContext import contextdefinition, renderoptions
from OpenGLContext.passes import tonemapping


GREY = np.array([1.0, 1.0, 1.0])


@pytest.mark.parametrize('operator, expected', [
    ('none', 1.0),
    # (2.51 + 0.03) / (2.43 + 0.59 + 0.14)
    ('aces_narkowicz', 2.54 / 3.16),
    # Hill's matrices keep grey grey: (1 + 0.0245786 - 0.000090537) / (0.983729 + 0.4329510 + 0.238081)
    ('aces_hill', 1.024488063 / 1.654761),
    # 1 / 0.6 through the same fit
    ('aces_hill_exposure_boost', 0.763397),
    # 1 - 0.04 is past 0.76: 1 - 0.24^2 / (0.96 + 0.24 - 0.76)
    ('khr_pbr_neutral', 1.0 - 0.0576 / 0.44),
])
def test_white_through_each_curve(operator, expected):
    assert tonemapping.tone_map(GREY, operator) == pytest.approx([expected] * 3, abs=2e-5)


def test_khr_pbr_neutral_below_its_knee_only_takes_the_offset():
    assert tonemapping.tone_map([0.5, 0.3, 0.2], 'khr_pbr_neutral') == pytest.approx(
        [0.46, 0.26, 0.16])
    # a dark minimum takes 6.25 x^2 off rather than 0.04
    assert tonemapping.tone_map([0.04, 0.5, 0.5], 'khr_pbr_neutral') == pytest.approx(
        [0.01, 0.47, 0.47])


def test_exposure_multiplies_before_the_curve():
    assert tonemapping.tone_map(GREY, 'none', exposure=0.5) == pytest.approx([0.5] * 3)
    assert tonemapping.tone_map(GREY * 2, 'aces_narkowicz', exposure=0.5) == pytest.approx(
        tonemapping.tone_map(GREY, 'aces_narkowicz'))


def test_hill_mixes_the_channels():
    """Hill's matrices work across channels: pure red's red is not white's"""
    red = tonemapping.tone_map([1.0, 0.0, 0.0], 'aces_hill')
    assert red == pytest.approx([0.68803, 0.0, 0.00264], abs=1e-5)


def test_an_unknown_curve_is_refused():
    with pytest.raises(ValueError):
        tonemapping.tone_map(GREY, 'reinhard')
    with pytest.raises(ValueError):
        tonemapping.untone(GREY, 'reinhard')


@pytest.mark.parametrize('operator', tonemapping.OPERATORS)
def test_untone_inverts_each_curve(operator):
    rng = np.random.default_rng(7)
    colours = rng.uniform(0.0, 1.5, size=(200, 3))
    shown = tonemapping.tone_map(colours, operator)
    kept = (shown.max(axis=-1) < 0.98) & (shown.min(axis=-1) > 0.0)
    back = tonemapping.tone_map(tonemapping.untone(shown[kept], operator), operator)
    assert back == pytest.approx(shown[kept], abs=2e-4)


@pytest.mark.parametrize('chosen, document, expected', [
    ('auto', True, 'none'),
    ('auto', False, 'aces_narkowicz'),
    ('khr_pbr_neutral', True, 'khr_pbr_neutral'),
    ('ACES_HILL', False, 'aces_hill'),
])
def test_the_curve_a_choice_draws_with(chosen, document, expected):
    assert tonemapping.resolve_operator(chosen, document) == expected


def test_an_unknown_choice_is_refused():
    with pytest.raises(ValueError):
        tonemapping.resolve_operator('filmic', False)
    with pytest.raises(ValueError):
        tonemapping.resolve_color_space('display_p3')


def test_auto_lights_physical_materials_in_linear_light():
    assert tonemapping.resolve_color_space('auto') == 'linear_when_physical_material'
    assert tonemapping.resolve_color_space('SRGB') == 'srgb'


def test_codes_are_the_shaders_order():
    assert [tonemapping.operator_code(name) for name in tonemapping.OPERATORS] == [0, 1, 2, 3, 4]
    assert tonemapping.color_space_code('linear') == 2


def _document_scene():
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    return Loader.loads(b"<X3D version='4.0'><Scene/></X3D>", 'a.x3d')


def test_a_document_is_displayed_as_x_ite_displays_it():
    shown = tonemapping.display(contextdefinition.ContextDefinition(), _document_scene())
    assert shown == tonemapping.Display(operator='none', exposure=1.0,
                                        color_space='linear_when_physical_material',
                                        document=True)


def test_a_scene_built_in_code_keeps_the_engines_curve():
    from OpenGLContext.scenegraph.basenodes import sceneGraph  # noqa: PLC0415 kept with its use
    shown = tonemapping.display(contextdefinition.ContextDefinition(), sceneGraph())
    assert (shown.operator, shown.document) == ('aces_narkowicz', False)


def test_the_definition_chooses():
    definition = contextdefinition.ContextDefinition(
        toneMapping='khr_pbr_neutral', exposure=0.5, colorSpace='linear')
    shown = tonemapping.display(definition, _document_scene())
    assert (shown.operator, shown.exposure, shown.color_space) == (
        'khr_pbr_neutral', 0.5, 'linear')


def test_a_negative_exposure_is_none():
    shown = tonemapping.display(contextdefinition.ContextDefinition(exposure=-2.0), None)
    assert shown.exposure == 0.0


def test_the_environment_is_the_default(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_TONE_MAPPING', 'ACES_HILL_EXPOSURE_BOOST')
    monkeypatch.setenv('OPENGLCONTEXT_EXPOSURE', '2')
    monkeypatch.setenv('OPENGLCONTEXT_COLOR_SPACE', 'srgb')
    renderoptions.reset_env_cache()
    shown = tonemapping.display(contextdefinition.ContextDefinition(), None)
    assert (shown.operator, shown.exposure, shown.color_space) == (
        'aces_hill_exposure_boost', 2.0, 'srgb')


def test_the_variables_are_rendering_settings():
    for name in ('OPENGLCONTEXT_TONE_MAPPING', 'OPENGLCONTEXT_EXPOSURE',
                 'OPENGLCONTEXT_COLOR_SPACE'):
        assert name in renderoptions.ENVIRONMENT


def test_a_settings_screen_offers_them():
    hints = contextdefinition.ContextDefinition.UI_HINTS
    assert hints['toneMapping']['options'] == tonemapping.TONE_MAPPING_CHOICES
    assert hints['colorSpace']['options'] == tonemapping.COLOR_SPACE_CHOICES
    for name in ('toneMapping', 'exposure', 'colorSpace'):
        assert name in contextdefinition.ContextDefinition.RENDERING_FIELDS
