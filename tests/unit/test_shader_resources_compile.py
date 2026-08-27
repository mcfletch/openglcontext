"""The GLSL the engine and its samples ship compiles in a core profile.

The shader sources under ``OpenGLContext/resources`` and ``tests/resources`` are
loaded by URL rather than imported, so nothing else would notice one of them
failing to compile until a demo drew nothing.
"""
import os
import time

import pytest
from vrml import cache

TESTS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class _Mode:
    """Enough of a pass for a ``GLSLObject`` to compile."""

    uniforms = ()

    def __init__(self):
        self.cache = cache.Cache()


@pytest.fixture
def in_the_tests_directory(monkeypatch):
    """The sample shaders are named by paths relative to ``tests/``."""
    monkeypatch.chdir(TESTS)
    monkeypatch.syspath_prepend(TESTS)
    yield


def loaded(objects, timeout=30.0):
    """Wait for every shader's source to arrive.

    A ``GLSLShader`` given a url fetches it on a thread of its own, so a shader
    asked to compile the instant it was declared has nothing to compile yet.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(shader.source for obj in objects for shader in obj.shaders):
            return
        time.sleep(0.05)
    missing = [shader.url for obj in objects for shader in obj.shaders
               if not shader.source]
    raise AssertionError('shader source never arrived: %s' % (missing,))


def test_every_shader_object_the_samples_declare_compiles(
    gl_context, in_the_tests_directory
):
    import shaderobjects

    objects = [appearance.objects[0] for appearance in shaderobjects.shaders]
    loaded(objects)
    failed = []
    for index, obj in enumerate(objects):
        program = obj.compile(_Mode())
        if not program:
            failed.append('%d: %s' % (index, obj.compileLog))
    assert not failed, '\n'.join(failed)


@pytest.mark.parametrize('resource', [
    'simpleshader_vert_txt',
    'simpleshader_frag_txt',
    'phongprecalc_vert',
    'phongweights_frag',
])
def test_the_shipped_shader_resources_are_core_glsl(resource):
    """Each names the version it is written in, and none reads a built-in the
    core profile removed."""
    module = __import__(
        'OpenGLContext.resources.%s' % (resource,), {}, {}, ['data'])
    # Comments name the built-ins they explain, so read the code alone.
    source = '\n'.join(
        line.split('//')[0]
        for line in module.data.decode('ascii').splitlines())
    removed = [name for name in (
        'gl_Vertex', 'gl_Normal', 'gl_Color', 'gl_FragColor', 'gl_TexCoord',
        'gl_MultiTexCoord0', 'gl_ModelViewProjectionMatrix', 'gl_NormalMatrix',
        'gl_LightSource', 'gl_FrontMaterial', 'ftransform',
        'attribute ', 'varying ',
    ) if name in source]
    assert not removed, '%s still reads %s' % (resource, ', '.join(removed))
