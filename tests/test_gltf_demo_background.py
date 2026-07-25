"""Per-model background resolution in the glTF sample browser.

The browser mutates ``config.background`` on every model swap (the base viewer
reads it from there), so the per-model fallback must come from the run's own
default, not from whatever the previously shown model left behind.
"""
from OpenGLContext.bin import gltf_demo


def _swap(config, name):
    """One model swap, as `TestContext._build_scenegraph` performs it."""
    config.background = gltf_demo.resolve_background(config, name)
    return config.background


def test_plain_model_stays_black_after_an_env_model():
    """A model with no env profile renders on black even when the previously
    browsed model pulled in a lit background.

    PlaysetLightTest's absolute-unit punctual lights are only exposed correctly
    on the black background; a leaked 'sky' clips the whole scene to white.
    """
    config = gltf_demo.demo_config([])

    assert _swap(config, 'NegativeScaleTest') == 'sky'
    assert _swap(config, 'PlaysetLightTest') == 'none'


def test_explicit_background_wins_for_every_model():
    config = gltf_demo.demo_config(['--background', 'sky'])

    assert _swap(config, 'PlaysetLightTest') == 'sky'
    assert _swap(config, 'NegativeScaleTest') == 'sky'


def test_env_profile_models_keep_their_background():
    config = gltf_demo.demo_config([])

    assert _swap(config, 'PlaysetLightTest') == 'none'
    assert _swap(config, 'NegativeScaleTest') == 'sky'
    assert _swap(config, 'PointLightIntensityTest') == 'none'
