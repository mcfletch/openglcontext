"""Regression lock: the unlit shader paths write the object id, not a hard 0.

Both shaders historically hard-coded ``fragObjectId = vec4(0.0)``, which made
every unlit fragment non-pickable. These are cheap source-level guards so a
future edit can't silently reintroduce that without a failing test (the GL
behaviour itself is covered by test_unlit_pickable_gl.py).
"""
import os

from OpenGLContext.testing.paths import tests_root
SHADERS = os.path.join(str(tests_root(__file__).parent),
                       'OpenGLContext', 'shaders')


def _read(name):
    with open(os.path.join(SHADERS, name)) as fh:
        return fh.read()


def test_pbr_unlit_branch_writes_object_id():
    src = _read('pbr.frag')
    # The KHR_materials_unlit early-out must encode the id, not zero it. The id is
    # the effective id (per-instance when instancing, else the per-draw uniform).
    assert 'fragObjectId = encodeObjectId(effectiveObjectId());' in src
    assert 'fragObjectId = vec4(0.0);' not in src


def test_vrml97_unlit_writes_object_id_for_geometry():
    src = _read('vrml97_unlit.frag')
    assert 'uniform uint objectId;' in src
    # Text stays non-pickable (guarded), real geometry encodes the id via the
    # shared helper; the shader must not hard-zero the geometry id.
    assert 'fragObjectId = encodeObjectId(objectId);' in src
    assert 'if (textMode)' in src
