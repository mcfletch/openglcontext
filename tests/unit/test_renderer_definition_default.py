"""A ContextDefinition's renderer field defaults to the environment's choice."""
import pytest

from OpenGLContext.contextdefinition import ContextDefinition


@pytest.mark.parametrize('environment, expected', [
    (None, 'pbr'),
    ('', 'pbr'),
    ('pbr', 'pbr'),
    ('vrml97', 'vrml97'),
    ('VRML97', 'vrml97'),
    ('nonsense', 'pbr'),
])
def test_renderer_default_follows_environment(monkeypatch, environment, expected):
    if environment is None:
        monkeypatch.delenv('OPENGLCONTEXT_RENDERER', raising=False)
    else:
        monkeypatch.setenv('OPENGLCONTEXT_RENDERER', environment)
    assert ContextDefinition().renderer == expected


def test_renderer_named_in_the_definition_wins(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_RENDERER', 'vrml97')
    assert ContextDefinition(renderer='pbr').renderer == 'pbr'
