"""The offscreen EGL context: device policy, and creating one for real.

Two layers, as elsewhere in this suite:

  * pure Python -- which EGL device the engine picks, and why.  This is where
    the interesting decision lives, and it needs no GPU and no display; what it
    does need is the bindings, so the module skips on a platform with no EGL
    library for them to bind to.
  * GL -- a real offscreen context, created, made current and drawn into.
    Skipped where PyOpenGL finds no EGL device to make one on.

The device policy is not cosmetic.  Asking for a display on a *hardware* EGL
device while ``LIBGL_ALWAYS_SOFTWARE`` demands software rendering is a
combination Mesa refuses and then segfaults on, so choosing the wrong device
here takes the process down rather than raising.
"""

import numpy as np
import pytest

pytest.importorskip('OpenGL.EGL', exc_type=ImportError)

from OpenGL import EGL
from OpenGL.EGL.devices import DeviceInfo, devices
from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, glClear, glClearColor, GL_RGB, GL_UNSIGNED_BYTE,
    glReadPixels, GL_CONTEXT_PROFILE_MASK, glGetIntegerv, GL_CONTEXT_CORE_PROFILE_BIT, GL_VERSION,
    glGetString,
)
from OpenGLContext import eglcontext, contextresources
from OpenGLContext.events import synthetic
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.windowsystem import egl as eglwindowsystem
from OpenGLContext.windowsystem.egl import EGLWindowSystem


def _needs_a_device():
    """Skip where PyOpenGL finds no EGL device to render on.

    Asked of PyOpenGL's enumeration rather than of the engine, so a context
    the engine fails to make on a machine that has a device fails the test.
    """
    if not devices():
        pytest.skip('no EGL device on this machine to make a context on')


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

    def test_a_gpu_serves_where_no_software_device_was_offered(self):
        """Wanting software and being offered only a GPU is refused, not
        substituted: Mesa will not force software rasterisation onto a display
        built on a hardware device, and having said so it dereferences the
        screen it declined to build. Rendering on the wrong sort of device does
        beat not rendering -- but this pair does not render, it dumps core."""
        with pytest.raises(eglcontext.EGLContextError,
                           match='LIBGL_ALWAYS_SOFTWARE'):
            eglcontext.chooseDevice(
                (device(0),), environ={'LIBGL_ALWAYS_SOFTWARE': '1'}
            )

    def test_falls_back_to_the_first_device_when_a_gpu_was_wanted(self):
        """The mismatch the other way round is only slow, so it still runs."""
        chosen = eglcontext.chooseDevice((device(0, software=True),), environ={})
        assert chosen.index == 0

    def test_an_explicit_index_wins(self):
        chosen = eglcontext.chooseDevice(
            (device(0), device(1, software=True)),
            environ={'OPENGLCONTEXT_EGL_DEVICE': '1'},
        )
        assert chosen.index == 1

    def test_an_explicit_gpu_with_software_demanded_is_refused(self):
        """Explicit or not, this is the pair that crashes; the caller is told
        which of the two settings to drop rather than losing the process."""
        with pytest.raises(eglcontext.EGLContextError) as raised:
            eglcontext.chooseDevice(
                (device(0), device(1, software=True)),
                environ={'OPENGLCONTEXT_EGL_DEVICE': '0',
                         'LIBGL_ALWAYS_SOFTWARE': '1'},
            )
        message = str(raised.value)
        assert 'OPENGLCONTEXT_EGL_DEVICE' in message
        assert 'LIBGL_ALWAYS_SOFTWARE' in message

    def test_an_explicit_index_naming_the_software_device_is_fine(self):
        chosen = eglcontext.chooseDevice(
            (device(0), device(1, software=True)),
            environ={'OPENGLCONTEXT_EGL_DEVICE': '1',
                     'LIBGL_ALWAYS_SOFTWARE': '1'},
        )
        assert chosen.index == 1

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
        assert _attribute(attributes, EGL.EGL_DEPTH_SIZE) == 24
        assert _attribute(attributes, EGL.EGL_STENCIL_SIZE) == 8

    def test_alpha_is_requested_only_when_asked_for(self):
        assert _attribute(eglcontext.configAttributes(alpha=True), EGL.EGL_ALPHA_SIZE) == 8
        assert _attribute(eglcontext.configAttributes(alpha=False), EGL.EGL_ALPHA_SIZE) == 0

    def test_multisampling_is_requested_only_when_asked_for(self):
        assert _attribute(
            eglcontext.configAttributes(multisampleSamples=4), EGL.EGL_SAMPLES
        ) == 4
        assert EGL.EGL_SAMPLES not in _attributes(eglcontext.configAttributes())

    def test_a_pbuffer_surface_is_requested(self):
        """There is no window, so the surface has to be one EGL can make alone."""
        assert _attribute(
            eglcontext.configAttributes(), EGL.EGL_SURFACE_TYPE
        ) == EGL.EGL_PBUFFER_BIT

    def test_the_list_is_terminated(self):
        attributes = eglcontext.configAttributes()
        assert attributes[-1] == EGL.EGL_NONE


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
        class KnownColour(eglcontext.EGLContext):
            """Clears to a colour no default framebuffer would hold by accident."""

            def Render(self, mode=None):
                eglcontext.EGLContext.Render(self, mode)
                glClearColor(0.25, 0.50, 0.75, 1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        _needs_a_device()
        context = KnownColour(size=(64, 48))
        try:
            yield context
        finally:
            context.close()

    def test_the_frame_holds_what_was_drawn(self, renderer):
        """The whole point: pixels come back, and they are the ones asked for."""
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
        device = renderer.windowsystem.device
        assert device is not None
        assert device.software == eglcontext.prefersSoftware()

    def test_closing_twice_is_harmless(self, renderer):
        """A caller that closes, and the fixture closing again, leave it closed."""
        renderer.close()
        renderer.close()
        assert renderer.windowsystem.display is None

    def test_it_works_as_a_context_manager(self):
        # Built here rather than through `renderer`, because what is under test
        # is the construction itself -- so the skip that fixture carries has to
        # be repeated: a machine with no EGL device cannot answer this one way
        # or the other, and must say so rather than fail.
        _needs_a_device()
        opened = eglcontext.EGLContext(size=(16, 16))
        with opened as context:
            assert context.windowsystem.display is not None
        assert context.windowsystem.display is None


class TestDrivingTheContext:
    """An offscreen context is still an interactive one: it can be driven.

    Nothing delivers events from outside, so a test supplies them through
    :mod:`OpenGLContext.events.synthetic` -- the same records telemetry replay
    and the out-of-process event injector use, sent by the same routes the
    platform would have used.
    """

    @pytest.fixture
    def context(self):
        _needs_a_device()
        context = eglcontext.EGLContext(size=(64, 64))
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
        # The pick readback is asynchronous by default, so the draw that takes
        # the event schedules it and a later frame delivers it.  How many
        # frames later is a property of how busy the machine is, so ask for it
        # rather than drawing a fixed number and hoping.
        context.OnDraw(force=1)
        context.flushPendingPicks()
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
        class KnownColour(eglcontext.EGLContext):
            def Render(self, mode=None):
                eglcontext.EGLContext.Render(self, mode)
                glClearColor(0.0, 1.0, 0.0, 1.0)
                glClear(GL_COLOR_BUFFER_BIT)

        _needs_a_device()
        context = KnownColour(size=(32, 32))
        try:
            yield context
        finally:
            context.close()

    def test_the_frame_comes_back_at_the_new_size(self, context):
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


class TestAFailedConstructionReleasesWhatItTook:
    """The module invites an application to try EGL and fall back, so a failure
    is an expected outcome rather than the end of the process -- and an
    initialised EGL display left behind on each attempt is a leak per attempt.
    """

    class _Stopped(Exception):
        pass

    def _context_failing_at(self, monkeypatch, step):
        """An EGLContext whose window system fails at one named step."""
        released = []

        monkeypatch.setattr(
            EGLWindowSystem, 'selectDevice',
            lambda _self: DeviceInfo(index=0, handle=object(), driver='test'),
        )
        monkeypatch.setattr(
            EGLWindowSystem, 'openDisplay',
            lambda _self, _device: 'display',
        )
        monkeypatch.setattr(
            EGLWindowSystem, 'chooseConfig', lambda _self, _definition: 'config'
        )
        monkeypatch.setattr(
            EGLWindowSystem, 'createContext',
            lambda _self, _definition, _config: 'context',
        )
        monkeypatch.setattr(
            EGLWindowSystem, 'createSurface',
            lambda _self, _config, _width, _height: 'surface',
        )
        monkeypatch.setattr(EGLWindowSystem, 'bind', lambda _self: None)
        monkeypatch.setattr(
            EGLWindowSystem, 'abandon',
            lambda self: released.append(
                (self.display, self.eglContext, self.surface)
            ),
        )

        def fails(*_args, **_named):
            raise eglcontext.EGLContextError('no')

        monkeypatch.setattr(EGLWindowSystem, step, fails)
        with pytest.raises(eglcontext.EGLContextError):
            eglcontext.EGLContext(size=(4, 4))
        return released

    @pytest.mark.parametrize(
        'step',
        ['chooseConfig', 'createContext', 'createSurface', 'bind'],
    )
    def test_the_display_is_released(self, monkeypatch, step):
        released = self._context_failing_at(monkeypatch, step)
        assert released, 'nothing was released after failing at %s' % (step,)
        assert released[0][0] == 'display'

    def test_nothing_is_released_that_was_never_taken(self, monkeypatch):
        released = self._context_failing_at(monkeypatch, 'chooseConfig')
        # The config failed, so there is no context and no surface to release.
        assert released[0][1] is None
        assert released[0][2] is None

    def test_the_engines_caches_are_not_told(self, monkeypatch):
        """No cache ever saw this context, so announcing its loss would drop
        another context's objects."""
        told = []
        monkeypatch.setattr(
            contextresources, 'context_lost', lambda: told.append(True)
        )
        self._context_failing_at(monkeypatch, 'createContext')
        assert told == []


def _unopened():
    """An EGLContext holding its window system, with nothing opened on EGL."""
    context = eglcontext.EGLContext.__new__(eglcontext.EGLContext)
    context.windowsystem = EGLWindowSystem(context)
    return context


class TestResizingRefusesADegenerateSize:
    """A size with a zero or negative dimension is not a surface."""

    @pytest.mark.parametrize(
        'size', [(0, 0), (0, 100), (100, 0), (-1, 100), (100, -1)]
    )
    def test_a_degenerate_size_is_refused(self, monkeypatch, size):
        """Every one of them: `(width, height) <= (0, 0)` is lexicographic
        ordering on tuples, which lets 100x0 and 100x-1 straight through."""
        made = []
        monkeypatch.setattr(
            EGLWindowSystem, 'createSurface',
            lambda _self, _config, width, height: made.append((width, height)),
        )
        instance = _unopened()
        with pytest.raises(eglcontext.EGLContextError) as caught:
            instance.OnResize(*size)
        assert 'cannot render at' in str(caught.value)
        assert made == [], 'a surface was made for %r' % (size,)


class TestFinishingAFrame:
    """``eglSwapBuffers`` on a pbuffer has no effect -- the EGL specification
    says so for any surface that is not a back-buffered window -- so it cannot
    be what guarantees the frame's commands have been issued."""

    def test_it_flushes(self, monkeypatch):
        flushed = []
        monkeypatch.setattr(eglwindowsystem, 'glFlush', lambda: flushed.append(True))
        instance = _unopened()
        instance.SwapBuffers()
        assert flushed == [True]


class TestConfigAttributesColourBuffer:
    def test_rgb_asks_for_an_rgb_buffer(self):
        attributes = eglcontext.configAttributes(rgb=True)
        pairs = dict(zip(attributes[::2], attributes[1::2], strict=False))
        assert pairs[EGL.EGL_COLOR_BUFFER_TYPE] == (
            EGL.EGL_RGB_BUFFER
        )
        assert pairs[EGL.EGL_RED_SIZE] == 8

    def test_not_rgb_asks_for_a_luminance_buffer(self):
        """A parameter that is accepted and ignored is worse than one that is
        absent: ``rgb=False`` used to leave EGL_RGB_BUFFER pinned and merely
        decline to say how many bits per channel."""
        attributes = eglcontext.configAttributes(rgb=False)
        pairs = dict(zip(attributes[::2], attributes[1::2], strict=False))
        assert pairs[EGL.EGL_COLOR_BUFFER_TYPE] == (
            EGL.EGL_LUMINANCE_BUFFER
        )
        assert EGL.EGL_RED_SIZE not in pairs


class TestFlushingPendingPicks:
    """A pick is read back asynchronously, so the click it carries arrives some
    frames after the draw that took it -- how many being a property of how busy
    the machine is rather than of the program.  A caller that has to act on the
    click before going on asks for it instead of drawing on and hoping.
    """

    @pytest.fixture
    def context(self):
        _needs_a_device()
        context = eglcontext.EGLContext(size=(64, 64))
        try:
            yield context
        finally:
            context.close()

    def _clicked(self, context):
        """Register a click handler, send a picked click, and return the list
        the handler appends to.

        The handler is held on the test instance because the event manager
        connects it by weak reference: a function this method alone referenced
        would be collected when it returned, and the click would be delivered
        to nothing.
        """
        clicks = []

        def onClick(event):
            clicks.append(event)

        self._handler = onClick
        context.addEventHandler('mousebutton', button=0, state=1,
                                function=onClick)
        synthetic.dispatch(context, {
            'type': 'mousebutton', 'button': 0, 'state': 1, 'x': 32, 'y': 32,
            'pick': True,
        })
        return clicks

    def test_one_frame_and_a_flush_deliver_the_click(self, context):
        """However the timing falls: the readback either is still in flight,
        and waiting for it delivers the click, or it landed mid-frame, and the
        cascade it was queued on is emptied."""
        clicks = self._clicked(context)
        context.OnDraw(force=1)
        context.flushPendingPicks()
        assert len(clicks) == 1

    def test_a_context_that_never_drew_has_nothing_to_flush(self, context):
        assert context.flushPendingPicks() == 0

    def test_flushing_twice_delivers_once(self, context):
        clicks = self._clicked(context)
        context.OnDraw(force=1)
        context.flushPendingPicks()
        context.flushPendingPicks()
        assert len(clicks) == 1


class TestContextAttributes:
    """The profile and version an EGL context is asked for.

    A case written against GLSL 330 in a core profile must get one, or it is
    testing a context nobody ships.
    """

    def test_the_version_asked_for_is_requested(self):
        attributes = eglcontext.contextAttributes('core', (4, 1))
        assert _attribute(attributes, EGL.EGL_CONTEXT_MAJOR_VERSION) == 4
        assert _attribute(attributes, EGL.EGL_CONTEXT_MINOR_VERSION) == 1

    def test_core_asks_for_the_core_profile(self):
        assert _attribute(
            eglcontext.contextAttributes('core'),
            EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK,
        ) == EGL.EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT

    def test_compatibility_asks_for_the_compatibility_profile(self):
        assert _attribute(
            eglcontext.contextAttributes('compatibility'),
            EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK,
        ) == EGL.EGL_CONTEXT_OPENGL_COMPATIBILITY_PROFILE_BIT

    def test_any_asks_for_nothing(self):
        """Below GL 3.2 there is no profile mask, so naming one refuses a
        context that would otherwise have been made."""
        assert eglcontext.contextAttributes('any') == [EGL.EGL_NONE]

    def test_forward_compatible_is_requested_only_when_asked_for(self):
        asked = eglcontext.contextAttributes('core', forwardCompatible=True)
        assert _attribute(
            asked, EGL.EGL_CONTEXT_OPENGL_FORWARD_COMPATIBLE
        ) == EGL.EGL_TRUE
        assert EGL.EGL_CONTEXT_OPENGL_FORWARD_COMPATIBLE not in _attributes(
            eglcontext.contextAttributes('core'))

    def test_a_profile_nobody_offers_is_a_programming_error(self):
        """A ValueError, not an EGLContextError: the name came from the
        caller's own source, and a caller that turned this into a skip would
        hide the typo forever."""
        with pytest.raises(ValueError, match='deluxe'):
            eglcontext.contextAttributes('deluxe')

    def test_the_list_is_terminated(self):
        assert eglcontext.contextAttributes('core')[-1] == EGL.EGL_NONE


class TestTheDefinitionsProfile:
    """An ``EGLContext`` is made with the profile and version its definition names.

    A core program run offscreen gets a core context, as it does in every
    windowed backend, so a fixed-function call fails the same way in both.
    """

    def _mask(self, profile):
        class Profiled(eglcontext.EGLContext):
            pass

        Profiled.profile = profile
        _needs_a_device()
        context = Profiled(size=(16, 16))
        try:
            context.setCurrent()
            try:
                return int(glGetIntegerv(GL_CONTEXT_PROFILE_MASK))
            finally:
                context.unsetCurrent()
        finally:
            context.close()

    def test_a_core_program_gets_a_core_context(self):
        assert self._mask('core') & GL_CONTEXT_CORE_PROFILE_BIT

    def test_the_definition_decides_the_attributes(self):
        core = eglcontext.definitionAttributes(
            ContextDefinition(profile='core', version=(4, 1)))
        assert _attribute(core, EGL.EGL_CONTEXT_MAJOR_VERSION) == 4
        assert _attribute(core, EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK) \
            == EGL.EGL_CONTEXT_OPENGL_CORE_PROFILE_BIT
        assert _attribute(core, EGL.EGL_CONTEXT_OPENGL_FORWARD_COMPATIBLE) \
            == EGL.EGL_TRUE

    def test_a_compatibility_program_with_no_version_takes_the_default(self):
        """Below GL 3.2 there is no profile to name, and (0, 0) names no version."""
        assert eglcontext.definitionAttributes(
            ContextDefinition(profile='compatibility', version=(0, 0))
        ) == [EGL.EGL_NONE]

    def test_a_compatibility_program_that_names_a_version_asks_for_it(self):
        attributes = eglcontext.definitionAttributes(
            ContextDefinition(profile='compatibility', version=(4, 5)))
        assert _attribute(attributes, EGL.EGL_CONTEXT_OPENGL_PROFILE_MASK) \
            == EGL.EGL_CONTEXT_OPENGL_COMPATIBILITY_PROFILE_BIT


class TestTheDisplayIsSharedRatherThanOwned:
    """``eglGetPlatformDisplayEXT`` answers the same display for the same
    device, and ``eglTerminate`` invalidates every context and surface on it.
    So a context that terminated on its way out would take its siblings down,
    and the suite opens two at once on purpose."""

    def test_the_last_user_out_terminates_it(self):
        _needs_a_device()
        device = eglcontext.selectDevice()
        first = eglcontext.openDisplay(device)
        second = eglcontext.openDisplay(device)
        assert eglwindowsystem._address(first) == eglwindowsystem._address(second)
        assert eglcontext.closeDisplay(second) is False
        assert eglcontext.closeDisplay(first) is True

    def test_two_pbuffer_contexts_live_at_once(self):
        """Releasing one leaves the other drawable."""
        _needs_a_device()
        first = eglcontext.PbufferContext(width=16, height=16)
        try:
            second = eglcontext.PbufferContext(width=16, height=16)
            second.release()
            first.make_current()
            assert glGetString(GL_VERSION) is not None
        finally:
            first.release()

    def test_releasing_one_leaves_the_current_one_current(self):
        """Letting go of a context that is not current un-currents nothing."""
        _needs_a_device()
        first = eglcontext.PbufferContext(width=16, height=16)
        try:
            second = eglcontext.PbufferContext(width=16, height=16)
            first.make_current()
            second.release()
            current = EGL.eglGetCurrentContext()
            assert eglwindowsystem._address(current) == eglwindowsystem._address(first.context)
        finally:
            first.release()
        assert not eglwindowsystem._address(EGL.eglGetCurrentContext())

    def test_releasing_twice_is_harmless(self):
        _needs_a_device()
        context = eglcontext.PbufferContext(width=16, height=16)
        context.release()
        context.release()
        assert context.display is None
