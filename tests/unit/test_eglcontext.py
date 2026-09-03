"""The offscreen EGL context: device policy, and creating one for real.

Two layers, as elsewhere in this suite:

  * pure Python -- which EGL device the engine picks, and why.  This is where
    the interesting decision lives, and it runs everywhere: no EGL, no GPU, no
    display.
  * GL -- a real offscreen context, created, made current and drawn into.
    Skipped where EGL cannot provide one.

The device policy is not cosmetic.  Asking for a display on a *hardware* EGL
device while ``LIBGL_ALWAYS_SOFTWARE`` demands software rendering is a
combination Mesa refuses and then segfaults on, so choosing the wrong device
here takes the process down rather than raising.
"""

import pytest

from OpenGL.EGL.devices import DeviceInfo
from OpenGLContext import eglcontext
from OpenGLContext.events import synthetic


def device(index=0, software=False, driver=None):
    """A DeviceInfo that is hardware or software, as asked."""
    if software:
        return DeviceInfo(index=index, handle=object(), extensions=('EGL_MESA_device_software',),
                          driver=driver or '')
    return DeviceInfo(index=index, handle=object(), extensions=('EGL_EXT_device_drm',),
                      driver=driver or 'radeonsi')


class TestPrefersSoftware:
    def test_a_bare_environment_wants_hardware(self):
        assert not eglcontext.prefersSoftware({})

    def test_libgl_always_software_demands_it(self):
        assert eglcontext.prefersSoftware({'LIBGL_ALWAYS_SOFTWARE': '1'})

    @pytest.mark.parametrize('value', ['', '0', 'false', 'False'])
    def test_the_off_spellings_do_not(self, value):
        assert not eglcontext.prefersSoftware({'LIBGL_ALWAYS_SOFTWARE': value})

    @pytest.mark.parametrize('value', ['true', 'yes', 'on'])
    def test_any_other_value_counts_as_on(self, value):
        """Mesa treats the variable as set-or-not, so anything else means yes."""
        assert eglcontext.prefersSoftware({'LIBGL_ALWAYS_SOFTWARE': value})

    def test_a_software_gallium_driver_demands_it(self):
        assert eglcontext.prefersSoftware({'GALLIUM_DRIVER': 'llvmpipe'})

    def test_a_hardware_gallium_driver_does_not(self):
        assert not eglcontext.prefersSoftware({'GALLIUM_DRIVER': 'radeonsi'})


class TestChooseDevice:
    def test_no_devices_is_no_choice(self):
        assert eglcontext.chooseDevice((), environ={}) is None

    def test_hardware_is_preferred_by_default(self):
        chosen = eglcontext.chooseDevice(
            (device(0, software=True), device(1)), environ={}
        )
        assert chosen.index == 1

    def test_software_is_chosen_when_the_environment_demands_it(self):
        """This is the case that segfaults if we get it wrong."""
        chosen = eglcontext.chooseDevice(
            (device(0), device(1, software=True)),
            environ={'LIBGL_ALWAYS_SOFTWARE': '1'},
        )
        assert chosen.index == 1

    def test_falls_back_to_the_first_device_when_the_preferred_kind_is_absent(self):
        """One device and a contrary preference still has to return something."""
        chosen = eglcontext.chooseDevice(
            (device(0),), environ={'LIBGL_ALWAYS_SOFTWARE': '1'}
        )
        assert chosen.index == 0

    def test_an_explicit_index_wins(self):
        chosen = eglcontext.chooseDevice(
            (device(0), device(1, software=True)),
            environ={'OPENGLCONTEXT_EGL_DEVICE': '1'},
        )
        assert chosen.index == 1

    def test_an_explicit_index_wins_over_the_software_preference(self):
        chosen = eglcontext.chooseDevice(
            (device(0), device(1, software=True)),
            environ={'OPENGLCONTEXT_EGL_DEVICE': '0', 'LIBGL_ALWAYS_SOFTWARE': '1'},
        )
        assert chosen.index == 0

    def test_an_out_of_range_index_is_refused_by_name(self):
        with pytest.raises(eglcontext.EGLContextError, match='OPENGLCONTEXT_EGL_DEVICE'):
            eglcontext.chooseDevice((device(0),), environ={'OPENGLCONTEXT_EGL_DEVICE': '7'})

    def test_a_non_numeric_index_is_refused_by_name(self):
        with pytest.raises(eglcontext.EGLContextError, match='OPENGLCONTEXT_EGL_DEVICE'):
            eglcontext.chooseDevice((device(0),), environ={'OPENGLCONTEXT_EGL_DEVICE': 'first'})

    def test_the_first_of_several_matching_devices_wins(self):
        chosen = eglcontext.chooseDevice(
            (device(0, software=True), device(1), device(2)), environ={}
        )
        assert chosen.index == 1


class TestConfigAttributes:
    """The EGL config request is built from the same ContextDefinition as every
    other backend, so an offscreen context honours the same settings."""

    def test_depth_and_stencil_come_from_the_definition(self):
        attributes = eglcontext.configAttributes(depthBuffer=24, stencilBuffer=8)
        assert _attribute(attributes, eglcontext.EGL.EGL_DEPTH_SIZE) == 24
        assert _attribute(attributes, eglcontext.EGL.EGL_STENCIL_SIZE) == 8

    def test_alpha_is_requested_only_when_asked_for(self):
        assert _attribute(eglcontext.configAttributes(alpha=True), eglcontext.EGL.EGL_ALPHA_SIZE) == 8
        assert _attribute(eglcontext.configAttributes(alpha=False), eglcontext.EGL.EGL_ALPHA_SIZE) == 0

    def test_multisampling_is_requested_only_when_asked_for(self):
        assert _attribute(
            eglcontext.configAttributes(multisampleSamples=4), eglcontext.EGL.EGL_SAMPLES
        ) == 4
        assert eglcontext.EGL.EGL_SAMPLES not in _attributes(eglcontext.configAttributes())

    def test_a_pbuffer_surface_is_requested(self):
        """There is no window, so the surface has to be one EGL can make alone."""
        assert _attribute(
            eglcontext.configAttributes(), eglcontext.EGL.EGL_SURFACE_TYPE
        ) == eglcontext.EGL.EGL_PBUFFER_BIT

    def test_the_list_is_terminated(self):
        attributes = eglcontext.configAttributes()
        assert attributes[-1] == eglcontext.EGL.EGL_NONE


def _attributes(attributes):
    """The token/value list as a dict, ignoring the EGL_NONE terminator."""
    values = list(attributes)
    return dict(zip(values[:-1:2], values[1::2], strict=True))


def _attribute(attributes, token):
    return _attributes(attributes).get(token, 0)


class TestOffscreenRendering:
    """A real offscreen context, rendering a real frame.

    An exit status proves nothing here -- a context that creates cleanly and
    draws nothing exits zero -- so these read the pixels back.
    """

    @pytest.fixture
    def renderer(self):
        from OpenGL.GL import (
            GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor,
        )

        class KnownColour(eglcontext.EGLContext):
            """Clears to a colour no default framebuffer would hold by accident."""

            def Render(self, mode=None):
                eglcontext.EGLContext.Render(self, mode)
                glClearColor(0.25, 0.50, 0.75, 1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        try:
            context = KnownColour(size=(64, 48))
        except eglcontext.EGLContextError as error:
            pytest.skip(f'no offscreen EGL context available here: {error}')
        try:
            yield context
        finally:
            context.close()

    def test_the_frame_holds_what_was_drawn(self, renderer):
        """The whole point: pixels come back, and they are the ones asked for."""
        import numpy as np
        from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels

        renderer.OnDraw(force=1)
        renderer.setCurrent()
        try:
            raw = glReadPixels(0, 0, 64, 48, GL_RGB, GL_UNSIGNED_BYTE)
        finally:
            renderer.unsetCurrent()
        pixels = np.frombuffer(bytes(raw), dtype=np.uint8).reshape(48, 64, 3)
        assert pixels.shape == (48, 64, 3)
        # Every pixel, not just one: a clear that only touched a corner would
        # otherwise read as a success.
        for channel, wanted in enumerate((0.25, 0.50, 0.75)):
            assert abs(float(pixels[..., channel].mean()) / 255 - wanted) < 0.02

    def test_the_surface_is_the_size_that_was_asked_for(self, renderer):
        assert tuple(int(value) for value in renderer.contextDefinition.size) == (64, 48)

    def test_it_rendered_on_the_device_the_policy_chose(self, renderer):
        assert renderer.device is not None
        assert renderer.device.software == eglcontext.prefersSoftware()

    def test_closing_twice_is_harmless(self, renderer):
        """Nothing should explode if a caller closes and the fixture closes again."""
        renderer.close()
        renderer.close()

    def test_it_works_as_a_context_manager(self):
        with eglcontext.EGLContext(size=(16, 16)) as context:
            assert context.display is not None
        assert context.display is None


class TestDrivingTheContext:
    """An offscreen context is still an interactive one: it can be driven.

    Nothing delivers events from outside, so a test supplies them through
    :mod:`OpenGLContext.events.synthetic` -- the same records telemetry replay
    and the out-of-process event injector use, sent by the same routes the
    platform would have used.
    """

    @pytest.fixture
    def context(self):
        try:
            context = eglcontext.EGLContext(size=(64, 64))
        except eglcontext.EGLContextError as error:
            pytest.skip(f'no offscreen EGL context available here: {error}')
        try:
            yield context
        finally:
            context.close()

    def test_a_key_record_reaches_a_registered_handler(self, context):
        pressed = []

        def onKey(event):
            pressed.append(event)

        # Handlers key on (name, state, modifiers), so a press registers state=1.
        context.addEventHandler('keyboard', name='w', state=1, function=onKey)
        assert synthetic.dispatch(
            context, {'type': 'keyboard', 'key': 'w', 'state': 1}
        )
        assert [event.name for event in pressed] == ['w']

    def test_a_click_record_reaches_a_registered_handler(self, context):
        clicks = []

        def onClick(event):
            clicks.append(event)

        context.addEventHandler('mousebutton', button=0, state=1, function=onClick)
        # Without `pick` the event skips the selection pass and is delivered
        # straight to the manager, which needs no render.
        assert synthetic.dispatch(context, {
            'type': 'mousebutton', 'button': 0, 'state': 1, 'x': 32, 'y': 32,
        })
        assert len(clicks) == 1

    def test_a_picked_click_is_delivered_by_the_selection_pass(self, context):
        clicks = []

        def onClick(event):
            clicks.append(event)

        context.addEventHandler('mousebutton', button=0, state=1, function=onClick)
        synthetic.dispatch(context, {
            'type': 'mousebutton', 'button': 0, 'state': 1, 'x': 32, 'y': 32,
            'pick': True,
        })
        # The pick readback is asynchronous by default, so it resolves a frame
        # or so after the draw that scheduled it.
        for _ in range(4):
            context.OnDraw(force=1)
            if clicks:
                break
        assert len(clicks) == 1

    def test_a_resize_record_reaches_the_context(self, context):
        """`resize` has no event object; dispatch calls OnResize as a backend does."""
        assert synthetic.dispatch(
            context, {'type': 'resize', 'width': 32, 'height': 16}
        )
        assert context.getViewPort() == (32, 16)


class TestResizing:
    """A pbuffer cannot be resized, so resizing replaces it.

    Reading pixels back at the new size is what shows the surface really
    changed rather than only the viewport.
    """

    @pytest.fixture
    def context(self):
        from OpenGL.GL import GL_COLOR_BUFFER_BIT, glClear, glClearColor

        class KnownColour(eglcontext.EGLContext):
            def Render(self, mode=None):
                eglcontext.EGLContext.Render(self, mode)
                glClearColor(0.0, 1.0, 0.0, 1.0)
                glClear(GL_COLOR_BUFFER_BIT)

        try:
            context = KnownColour(size=(32, 32))
        except eglcontext.EGLContextError as error:
            pytest.skip(f'no offscreen EGL context available here: {error}')
        try:
            yield context
        finally:
            context.close()

    def test_the_frame_comes_back_at_the_new_size(self, context):
        import numpy as np
        from OpenGL.GL import GL_RGB, GL_UNSIGNED_BYTE, glReadPixels

        context.OnResize(48, 24)
        context.OnDraw(force=1)
        context.setCurrent()
        try:
            raw = glReadPixels(0, 0, 48, 24, GL_RGB, GL_UNSIGNED_BYTE)
        finally:
            context.unsetCurrent()
        pixels = np.frombuffer(bytes(raw), dtype=np.uint8).reshape(24, 48, 3)
        assert float(pixels[..., 1].mean()) > 200      # green, everywhere

    def test_the_viewport_follows(self, context):
        context.OnResize(48, 24)
        assert context.getViewPort() == (48, 24)

    def test_a_zero_size_is_refused(self, context):
        with pytest.raises(eglcontext.EGLContextError):
            context.OnResize(0, 0)
