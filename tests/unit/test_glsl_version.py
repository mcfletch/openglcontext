"""``glsl_version`` reports what the driver's shading language is.

``glGetString`` answers bytes, and a driver is free to put its own text after
the version number -- "3.30 NVIDIA via Cg compiler" -- so both have to be dealt
with before the digits can be read.
"""

import pytest

from OpenGLContext.scenegraph.shaders import glsl_version


def test_the_running_driver_reports_a_major_and_a_minor(gl_context):
    major, minor = glsl_version()
    assert isinstance(major, int) and isinstance(minor, int)
    # The engine's shaders are #version 330 core, so anything that runs them
    # reports at least that.
    assert (major, minor) >= (3, 30)


@pytest.mark.parametrize(
    'reported, expected',
    [
        (b'4.60', [4, 60]),
        (b'3.30', [3, 30]),
        (b'3.30 NVIDIA via Cg compiler', [3, 30]),
        ('4.10 - Build 27.20', [4, 10]),
    ],
)
def test_a_vendor_suffix_is_not_part_of_the_version(monkeypatch, reported, expected):
    from OpenGLContext.scenegraph import shaders

    monkeypatch.setattr(shaders, 'glGetString', lambda which: reported)
    assert shaders.glsl_version() == expected
