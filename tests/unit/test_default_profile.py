"""A program that asks for nothing gets a core profile.

The pipeline a compatibility profile exists for has been deprecated since OpenGL
3.0, is absent from core contexts, from macOS 3.2 and above, from GLES and from
any driver that offers core alone -- and the engine's own primary geometry node,
:class:`~OpenGLContext.scenegraph.pbrmesh.PBRMesh`, is shader-only and draws
nothing there.  So core is what a caller gets for free, and compatibility is
what a program asks for when it means to use the older pipeline.
"""

import numpy as np
import pytest

pytest_plugins = ['tests.unit.test_passes_render_gl']

from OpenGLContext.contextdefinition import (  # noqa: E402
    ContextDefinition, _get_default_profile, version_for_profile,
)


class TestTheDefault:
    def test_asking_for_nothing_gives_core(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PROFILE', raising=False)
        assert _get_default_profile() == 'core'

    def test_a_definition_made_with_no_arguments_is_core(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PROFILE', raising=False)
        assert ContextDefinition().profile == 'core'

    def test_the_default_carries_the_version_core_needs(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PROFILE', raising=False)
        assert tuple(ContextDefinition().version) == version_for_profile('core')

    def test_the_environment_still_names_the_other_one(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'compatibility')
        assert ContextDefinition().profile == 'compatibility'

    def test_a_program_still_asks_for_compatibility_itself(self, monkeypatch):
        monkeypatch.delenv('OPENGLCONTEXT_PROFILE', raising=False)
        assert ContextDefinition(profile='compatibility').profile == 'compatibility'


class TestGeneratedGeometryDrawsWithNothingSet:
    """The failure this whole change is for, stated as a test.

    A mesh built through ``frommesh`` -- which is what the glTF loader and every
    generator produce -- is a ``PBRMesh``, and a ``PBRMesh`` draws only under a
    shader.  With no profile named anywhere, it has to reach the framebuffer.
    """

    @pytest.fixture(autouse=True)
    def no_profile_named(self, monkeypatch):
        from tests.unit.test_passes_render_gl import _base_env
        _base_env(monkeypatch)
        monkeypatch.delenv('OPENGLCONTEXT_PROFILE', raising=False)

    def test_the_context_opens_a_core_profile(self, render_scene):
        rendered = render_scene(generated_mesh_scene(), frames=2)
        assert rendered.context.contextDefinition.profile == 'core'

    def test_a_generated_mesh_reaches_the_framebuffer(self, render_scene):
        from OpenGLContext import glfwcontext
        from OpenGLContext.capture import read_back_buffer

        frames = []
        original = glfwcontext.GLFWContext.SwapBuffers

        def capturing(self):
            frames.append(read_back_buffer()[0])
            return original(self)

        glfwcontext.GLFWContext.SwapBuffers = capturing
        try:
            render_scene(generated_mesh_scene(), frames=4)
        finally:
            glfwcontext.GLFWContext.SwapBuffers = original
        assert frames, 'nothing was rendered'
        assert np.asarray(frames[-1]).max() > 0, 'the frame is black'

    def test_nothing_failed_to_render(self, render_scene):
        from OpenGLContext.passes import renderpass
        render_scene(generated_mesh_scene(), frames=3)
        assert renderpass.FLAT.failures.summary() == []


def generated_mesh_scene():
    """A quad built the way the glTF loader and the generators build one."""
    from types import SimpleNamespace

    from OpenGLContext.scenegraph import basenodes
    from OpenGLContext.scenegraph.frommesh import mesh_from_primitive
    from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial

    positions = np.array([
        [-4, -4, -20], [4, -4, -20], [4, 4, -20],
        [-4, -4, -20], [4, 4, -20], [-4, 4, -20],
    ], 'f')
    normals = np.tile(np.array([0, 0, 1], 'f'), (6, 1))
    mesh = mesh_from_primitive(
        SimpleNamespace(attributes={'POSITION': positions, 'NORMAL': normals},
                        indices=None),
        material=PBRMaterial(baseColor=(0.8, 0.1, 0.1)))
    return [basenodes.Shape(geometry=mesh),
            basenodes.PointLight(location=(0, 5, 0), intensity=1.0)]
