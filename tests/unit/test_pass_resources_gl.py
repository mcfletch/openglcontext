"""A replaced render pass gives its GL objects back (GL, PBR core).

A new scenegraph builds a new pass for the context, and the pass it replaces
holds textures, framebuffers, buffers, queries and programs in a context that
is still alive. Each is named here and asked of the driver after the swap.
"""
import gc

import pytest

glfw = pytest.importorskip("glfw")

from OpenGL import GL

from OpenGLContext.scenegraph import basenodes
from tests.unit.glrender import base_env
from tests.unit.test_planar_mirror_gl import _room
from OpenGLContext.passes import renderpass

SIZE = (160, 120)


@pytest.fixture
def env(monkeypatch):
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='1', OPENGLCONTEXT_INSTANCE_MIN='999',
             OPENGLCONTEXT_IBL='full', OPENGLCONTEXT_BLOOM='1')
    return monkeypatch


def _names(pass_):
    """Every GL name ``pass_`` holds that the driver can be asked about."""
    held = []

    def add(kind, name):
        if name:
            held.append((kind, int(name)))

    atlas = pass_._reflection_atlas
    if atlas is not None:
        add('texture', atlas.texture)
        add('framebuffer', atlas.framebuffer)
    timer = pass_._reflection_timer
    if timer is not None:
        for query in timer._queries:
            add('query', query)
    probe = pass_._ibl_probe
    if probe is not None:
        for attribute in ('env', 'irradiance', 'prefilter', 'brdf'):
            add('texture', getattr(probe, attribute, None))
    bloom = pass_._bloom_pass
    if bloom is not None and bloom._targets is not None:
        add('texture', bloom._targets.scene_tex)
        add('framebuffer', bloom._targets.scene_fbo)
    if bloom is not None and bloom._chain is not None:
        add('program', bloom._chain.composite)
    add('buffer', pass_._viewTable)
    shader = pass_._shader_program_instance
    if shader is not None:
        for attribute in shader._PROGRAM_ATTRS:
            add('program', getattr(shader, attribute, None))
    array = pass_._shared_array
    if array is not None:
        add('texture', array.depth_texture)
    return held


_ASK = {
    'texture': GL.glIsTexture,
    'framebuffer': GL.glIsFramebuffer,
    'renderbuffer': GL.glIsRenderbuffer,
    'query': GL.glIsQuery,
    'buffer': GL.glIsBuffer,
    'program': GL.glIsProgram,
}


def _alive(held):
    return [(kind, name) for kind, name in held if _ASK[kind](name)]


def _census(ceiling=4096):
    """How many objects of each kind the context holds.

    A name the driver freed is handed out again, so asking after one name
    says nothing once the next pass has allocated; a count that grows with
    every swap is what a leak looks like.
    """
    return {kind: sum(1 for name in range(1, ceiling) if ask(name))
            for kind, ask in _ASK.items()}


def _swap(context):
    """Draw a new scene; the old one's nodes are collected and their buffers go."""
    context.sg = basenodes.sceneGraph(children=_room())
    context.OnDraw(force=1)
    gc.collect()
    context.OnDraw(force=1)


@pytest.mark.usefixtures('env')
def test_a_scene_swap_releases_the_outgoing_passs_gl_objects(render_scene):
    rendered = render_scene(_room(), frames=3, size=SIZE)
    context = rendered.context
    outgoing = renderpass.current_pass()
    held = _names(outgoing)
    kinds = {kind for kind, _name in held}
    # The scene exercised what the pass allocates: a mirror, the probe, bloom,
    # shadows and the programs.
    assert {'texture', 'framebuffer', 'program', 'query'} <= kinds, held
    assert len(_alive(held)) == len(held)

    _swap(context)
    settled = _census()
    _swap(context)
    _swap(context)

    assert renderpass.current_pass() is not outgoing
    assert _names(outgoing) == []
    assert _census() == settled


@pytest.mark.usefixtures('env')
def test_disposing_twice_is_harmless(render_scene):
    render_scene(_room(), frames=2, size=SIZE)
    pass_ = renderpass.current_pass()
    held = _names(pass_)
    pass_.disposeResources()
    pass_.disposeResources()
    assert _names(pass_) == []
    assert _alive(held) == []


@pytest.mark.usefixtures('env')
def test_a_pass_draws_again_after_disposing(render_scene):
    """What disposing drops is made again on the next frame that needs it."""
    rendered = render_scene(_room(), frames=2, size=SIZE)
    pass_ = renderpass.current_pass()
    before = {kind for kind, _name in _names(pass_)}
    pass_.disposeResources()
    rendered.context.OnDraw(force=1)
    rendered.context.OnDraw(force=1)
    assert renderpass.current_pass() is pass_
    again = _names(pass_)
    assert {kind for kind, _name in again} == before
    # A query exists once it has been begun, and the timer begins one a frame.
    made = [(kind, name) for kind, name in again if kind != 'query']
    assert len(_alive(made)) == len(made)
