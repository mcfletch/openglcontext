"""Choosing which catalogue model the glTF sample browser opens on."""
import pytest

from OpenGLContext.bin import gltf_demo


CATALOG = ['ABeautifulGame', 'BoomBox', 'DamagedHelmet', 'PlaysetLightTest']


def test_model_defaults_to_the_environment_variable(monkeypatch):
    monkeypatch.setenv('MODEL', 'DamagedHelmet')

    assert gltf_demo.demo_config([]).model == 'DamagedHelmet'


def test_model_defaults_to_empty_without_the_environment_variable(monkeypatch):
    monkeypatch.delenv('MODEL', raising=False)

    assert gltf_demo.demo_config([]).model == ''


def test_model_option_overrides_the_environment_variable(monkeypatch):
    monkeypatch.setenv('MODEL', 'DamagedHelmet')

    assert gltf_demo.demo_config(['--model', 'BoomBox']).model == 'BoomBox'


@pytest.mark.parametrize('start,expected', [
    ('', 0),                    # unset: open on the first model
    ('PlaysetLightTest', 3),    # by name
    ('BoomBox', 1),
    ('2', 2),                   # by catalogue index
    ('5', 1),                   # index wraps
    ('NoSuchModel', 0),         # unknown name: first model, not a crash
])
def test_start_index_resolution(start, expected):
    assert gltf_demo.resolve_start_index(CATALOG, start) == expected


def test_start_index_of_an_empty_catalogue_is_zero():
    assert gltf_demo.resolve_start_index([], '3') == 0
