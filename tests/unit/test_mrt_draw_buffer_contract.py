"""The MRT object-id draw-buffer contract.

Every main-scene fragment shader gained a second output,
``layout(location = 1) out vec4 fragObjectId``, so the selection buffer can be
filled in the same pass that draws colour. That is only safe while a strict
contract holds:

1. Object-id output is ALWAYS at location 1, and location 1 is reserved for it
   across every shader -- no shader may put a *different* semantic there, or that
   data would be silently lost on any single-attachment (non-MRT) target.
2. Colour output is ALWAYS at location 0.
3. Offscreen helper shaders that render to a single-attachment FBO (the IBL
   bake passes) must NOT declare a location-1 output -- writing one there targets
   a non-existent attachment.
4. The MRT selection FBO actually provides attachment 1 and enables both draw
   buffers, so the location-1 writes land somewhere.

On the default framebuffer (the ordinary on-screen non-MRT path) draw buffer 1
is GL_NONE by spec, so the location-1 writes are harmlessly discarded; these
tests lock the parts we control so a newly added shader can't break the contract.
"""
import os
import re

import pytest

from OpenGLContext.passes.shaderpass import SHADER_DIR
from OpenGLContext.passes import selection
from OpenGLContext.passes import selectionbuffers


_OUT_RE = re.compile(r'layout\s*\(\s*location\s*=\s*(\d+)\s*\)\s*out\s+vec\d+\s+(\w+)')

# Main-scene shaders that participate in MRT picking: colour + object id.
MRT_SCENE_SHADERS = [
    'vrml97_lighting.frag', 'vrml97_point.frag', 'vrml97_unlit.frag',
    'vrml97_background.frag', 'vrml97_vertex_color.frag', 'vrml97_line.frag',
    'pbr.frag',
]
# Offscreen bake passes: single-attachment targets, must stay single-output.
OFFSCREEN_SHADERS = [f for f in os.listdir(SHADER_DIR) if f.startswith('ibl_')]

OBJECT_ID_NAME = 'fragObjectId'
OBJECT_ID_LOCATION = 1
COLOR_LOCATION = 0


def _located_outputs(name):
    with open(os.path.join(SHADER_DIR, name)) as f:
        src = f.read()
    return {int(loc): ident for loc, ident in _OUT_RE.findall(src)}


def _all_frags():
    return [f for f in os.listdir(SHADER_DIR) if f.endswith('.frag')]


class TestObjectIdSlotReserved:
    def test_location_1_is_always_object_id(self):
        """No shader may repurpose location 1 for anything but the object id."""
        for frag in _all_frags():
            outs = _located_outputs(frag)
            if OBJECT_ID_LOCATION in outs:
                assert outs[OBJECT_ID_LOCATION] == OBJECT_ID_NAME, (
                    f"{frag}: location 1 is {outs[OBJECT_ID_LOCATION]!r}, but that "
                    "slot is reserved for the object id and would be lost on a "
                    "single-attachment target"
                )

    @pytest.mark.parametrize('frag', MRT_SCENE_SHADERS)
    def test_scene_shaders_declare_colour0_and_objectid1(self, frag):
        outs = _located_outputs(frag)
        assert outs.get(COLOR_LOCATION) == 'fragColor', f"{frag} colour must be location 0"
        assert outs.get(OBJECT_ID_LOCATION) == OBJECT_ID_NAME, \
            f"{frag} object id must be location 1"


class TestOffscreenShadersSingleOutput:
    @pytest.mark.parametrize('frag', OFFSCREEN_SHADERS)
    def test_no_object_id_on_single_attachment_targets(self, frag):
        outs = _located_outputs(frag)
        assert OBJECT_ID_LOCATION not in outs, (
            f"{frag} renders to a single-attachment FBO; a location-1 output would "
            "write to a non-existent attachment"
        )


class TestSelectionFBOProvidesAttachment1:
    """The one runtime path that expects the location-1 writes must actually
    supply attachment 1 and enable both draw buffers."""

    def _src(self):
        import inspect
        # The selection FBOs (attachment 1 + both draw buffers) live in
        # selectionbuffers; the pick policy in selection drives them.
        return inspect.getsource(selection) + inspect.getsource(selectionbuffers)

    def test_fbo_creates_color_attachment1(self):
        src = self._src()
        assert 'GL_COLOR_ATTACHMENT1' in src

    def test_both_draw_buffers_enabled(self):
        src = self._src()
        assert re.search(
            r'glDrawBuffers\(\s*2\s*,\s*\[\s*GL_COLOR_ATTACHMENT0\s*,\s*GL_COLOR_ATTACHMENT1\s*\]',
            src,
        ), "MRT bind must enable both colour draw buffers so the id write lands"


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
