"""The offscreen WGL context: what a definition asks for, and asking for it.

Two layers, as in :mod:`test_eglcontext`:

  * pure Python -- what a :class:`ContextDefinition` becomes when it is handed
    to WGL.  That is where the decisions live, and it runs everywhere: no
    Windows, no driver, no display.  A Linux run therefore holds the Windows
    path to its contract.
  * GL -- a real offscreen context, created, made current and drawn into.
    Windows only, and skipped where the driver offers no pbuffers.

The pure half is worth holding closely.  A profile bit sent with a request
below GL 3.2 makes the driver refuse the whole context, and a double buffer
nobody swaps is memory spent on a surface that is never presented; neither is
visible in a passing run on a machine with no WGL.
"""

import sys

import pytest

from OpenGLContext import contextdefinition, wglcontext
from OpenGLContext.events import synthetic

windows_only = pytest.mark.skipif(
    sys.platform != 'win32', reason='WGL is the Windows binding for OpenGL')


def definition(**named):
    return contextdefinition.ContextDefinition(**named)


class TestWhichPixelFormatsAreAccepted:
    """A format the GPU does not draw is slow rather than wrong, so the
    environment can ask for one on an adapter that advertises no accelerated
    pbuffer format."""

    def test_a_bare_environment_demands_acceleration(self):
        assert wglcontext.acceleration({}) == 'accelerated'

    @pytest.mark.parametrize('value', ['1', 'true', 'yes', 'on'])
    def test_the_variable_relaxes_it(self, value):
        assert wglcontext.acceleration(
            {wglcontext.ACCELERATION_VARIABLE: value}) == 'any'

    @pytest.mark.parametrize('value', ['', '0', 'false', 'no', 'off'])
    def test_the_off_spellings_do_not(self, value):
        """An unset variable and an empty one mean the same thing, which is
        what an unexported shell variable expands to."""
        assert wglcontext.acceleration(
            {wglcontext.ACCELERATION_VARIABLE: value}) == 'accelerated'


class TestTheBuffersADefinitionAsksFor:
    """The whole of the translation between this package's settings and WGL's."""

    def test_depth_and_stencil_come_from_the_definition(self):
        asked = wglcontext.bufferSizes(definition(depthBuffer=32, stencilBuffer=8))
        assert asked['depth_bits'] == 32
        assert asked['stencil_bits'] == 8

    def test_an_unset_depth_buffer_becomes_the_usual_one(self):
        """``-1`` means "the driver picks"; a depth buffer of nothing is not
        what a scene with geometry in it wants."""
        assert wglcontext.bufferSizes(definition(depthBuffer=-1))['depth_bits'] == 24

    def test_alpha_is_requested_only_when_asked_for(self):
        assert wglcontext.bufferSizes(definition(alpha=True))['alpha_bits'] == 8
        assert wglcontext.bufferSizes(definition(alpha=False))['alpha_bits'] == 0

    def test_multisampling_is_requested_only_when_asked_for(self):
        assert wglcontext.bufferSizes(
            definition(multisampleSamples=4))['samples'] == 4
        assert wglcontext.bufferSizes(
            definition(multisampleSamples=-1))['samples'] == 0

    def test_it_is_single_buffered_whatever_the_definition_says(self):
        """Nothing presents a pbuffer -- SwapBuffers is a flush -- so a back
        buffer would be memory spent on nothing."""
        assert wglcontext.bufferSizes(
            definition(doubleBuffer=True))['double_buffer'] is False

    def test_every_key_is_one_the_offscreen_module_takes(self):
        """The two are separate packages, so the shape of the call between them
        is worth stating rather than discovering at run time."""
        import inspect

        from OpenGL.WGL import offscreen

        accepted = set(
            inspect.signature(offscreen.pixel_format_attributes).parameters)
        assert set(wglcontext.bufferSizes(definition())) <= accepted


class TestTheProfileADefinitionAsksFor:
    def test_core_is_carried_through(self):
        assert wglcontext.profileFor(
            definition(profile='core', version=(3, 3))) == ('core', (3, 3))

    def test_compatibility_is_carried_through(self):
        assert wglcontext.profileFor(
            definition(profile='compatibility', version=(4, 6))
        ) == ('compatibility', (4, 6))

    @pytest.mark.parametrize('version', [(2, 1), (3, 0), (3, 1)])
    def test_below_3_2_names_no_profile(self, version):
        """The profile mask arrived with GL 3.2, and a driver handed one below
        that refuses the whole request rather than ignoring it."""
        profile, _version = wglcontext.profileFor(
            definition(profile='core', version=version))
        assert profile == 'legacy'

    def test_a_version_nobody_chose_becomes_one_the_driver_can_answer(self):
        """``(0, 0)`` means "let the driver choose", which
        wglCreateContextAttribsARB has no way to say."""
        assert wglcontext.profileFor(
            definition(profile='compatibility', version=(0, 0))
        ) == ('legacy', (1, 1))

    def test_the_profile_names_are_ones_the_offscreen_module_offers(self):
        from OpenGL.WGL import offscreen

        for profile in ('core', 'compatibility'):
            for version in ((3, 2), (4, 6), (2, 1)):
                named, _ = wglcontext.profileFor(
                    definition(profile=profile, version=version))
                assert named in offscreen.PROFILES


@windows_only
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

        class KnownColour(wglcontext.WGLContext):
            """Clears to a colour no default framebuffer would hold by accident."""

            def Render(self, mode=None):
                wglcontext.WGLContext.Render(self, mode)
                glClearColor(0.25, 0.50, 0.75, 1.0)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

        try:
            context = KnownColour(size=(64, 48))
        except wglcontext.WGLContextError as error:
            pytest.skip(f'no offscreen WGL context available here: {error}')
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
        assert (renderer.surface.width, renderer.surface.height) == (64, 48)

    def test_the_viewport_is_the_size_that_was_asked_for(self, renderer):
        assert renderer.getViewPort() == (64, 48)

    def test_closing_twice_is_harmless(self, renderer):
        """Nothing should explode if a caller closes and the fixture closes again."""
        renderer.close()
        renderer.close()

    def test_it_works_as_a_context_manager(self):
        # Built here rather than through `renderer`, because what is under test
        # is the construction itself -- so the skip that fixture carries has to
        # be repeated: a machine with no pbuffers cannot answer this one way or
        # the other, and must say so rather than fail.
        try:
            opened = wglcontext.WGLContext(size=(16, 16))
        except wglcontext.WGLContextError as error:
            pytest.skip(f'no offscreen WGL context available here: {error}')
        with opened as context:
            assert context.surface is not None
        assert context.surface is None


@windows_only
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
            context = wglcontext.WGLContext(size=(64, 64))
        except wglcontext.WGLContextError as error:
            pytest.skip(f'no offscreen WGL context available here: {error}')
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


@windows_only
class TestResizing:
    """A pbuffer cannot be resized, so resizing replaces it.

    Reading pixels back at the new size is what shows the surface really
    changed rather than only the viewport.
    """

    @pytest.fixture
    def context(self):
        from OpenGL.GL import GL_COLOR_BUFFER_BIT, glClear, glClearColor

        class KnownColour(wglcontext.WGLContext):
            def Render(self, mode=None):
                wglcontext.WGLContext.Render(self, mode)
                glClearColor(0.0, 1.0, 0.0, 1.0)
                glClear(GL_COLOR_BUFFER_BIT)

        try:
            context = KnownColour(size=(32, 32))
        except wglcontext.WGLContextError as error:
            pytest.skip(f'no offscreen WGL context available here: {error}')
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

    def test_the_definition_follows(self, context):
        """A capture reads the size off the definition, so it has to agree with
        the surface rather than with what was first asked for."""
        context.OnResize(48, 24)
        assert tuple(int(v) for v in context.contextDefinition.size) == (48, 24)

    @pytest.mark.parametrize('size', [(0, 0), (0, 100), (100, 0),
                                      (-1, 100), (100, -1)])
    def test_a_degenerate_size_is_refused(self, context, size):
        """Every one of them: `(width, height) <= (0, 0)` is lexicographic
        ordering on tuples, which lets 100x0 and 100x-1 straight through."""
        with pytest.raises(wglcontext.WGLContextError):
            context.OnResize(*size)


@windows_only
class TestHowManyFramesTheLoopDraws:
    """``frameCount`` is the floor, not the ceiling.

    An offscreen ``MainLoop`` has no user to wait for, so it draws a set number
    of frames and returns -- and one is the right number for "render an image,
    read it back". But a settle capture draws until the scene has converged and
    a recording until it has enough frames, and neither knows in advance how
    many that is. So the loop also asks whether anything still wants one.
    """

    def contextDrawing(self, wanted):
        """A context that reports it wants ``wanted`` more frames, counting."""
        class Counting(wglcontext.WGLContext):
            drawn = 0
            remaining = wanted

            def Render(self, mode=None):
                wglcontext.WGLContext.Render(self, mode)
                self.drawn += 1
                self.remaining = max(0, self.remaining - 1)

            def wantsMoreFrames(self):
                return bool(self.remaining)

        try:
            return Counting(size=(16, 16))
        except wglcontext.WGLContextError as error:
            pytest.skip(f'no offscreen WGL context available here: {error}')

    def test_it_draws_the_frame_count_when_nothing_wants_more(self):
        context = self.contextDrawing(0)
        context.MainLoop()
        assert context.drawn == 1

    def test_it_keeps_drawing_while_something_wants_more(self):
        """What a settle capture needs: the ten frames and the half second it
        waits for are more than the one frame `frameCount` asks for."""
        context = self.contextDrawing(5)
        context.MainLoop()
        assert context.drawn == 5

    def test_the_frame_count_is_still_a_floor(self):
        context = self.contextDrawing(0)
        context.frameCount = 3
        context.MainLoop()
        assert context.drawn == 3


class TestWhetherAnythingWantsAnotherFrame:
    """The question the offscreen loops ask, and who answers it.

    Several mixins may have an opinion at once -- a viewer recording a capture
    is both -- so each answers for itself and passes the question on rather
    than replacing the answer.
    """

    def test_a_context_with_nothing_pending_wants_none(self):
        from OpenGLContext import context as contextmodule

        instance = contextmodule.Context.__new__(contextmodule.Context)
        assert instance.wantsMoreFrames() is False

    def test_a_settle_capture_wants_frames_until_it_has_taken_one(self):
        from OpenGLContext.viewer.capture import SettleCaptureMixin

        class Viewer(SettleCaptureMixin):
            pass

        viewer = Viewer()
        viewer.setupCapture(None)
        assert viewer.wantsMoreFrames() is False
        viewer.setupCapture('somewhere.png')
        assert viewer.wantsMoreFrames() is True
        viewer.settleCapture.done = True
        assert viewer.wantsMoreFrames() is False

    def test_a_recording_wants_frames_while_it_is_running(self):
        from OpenGLContext.video.recorder import RecordingMixin

        class Viewer(RecordingMixin):
            pass

        viewer = Viewer()
        viewer.setupRecording(None)
        assert viewer.wantsMoreFrames() is False
        viewer.recorder = object()          # stands in for a live recording
        assert viewer.wantsMoreFrames() is True

    def test_each_asks_the_next_rather_than_answering_for_it(self):
        """A viewer that records *and* captures has two of these in its bases,
        and the frames one of them still wants are frames the loop must draw
        whatever the other says."""
        from OpenGLContext.video.recorder import RecordingMixin
        from OpenGLContext.viewer.capture import SettleCaptureMixin

        class Base:
            def wantsMoreFrames(self):
                return False

        class Viewer(SettleCaptureMixin, RecordingMixin, Base):
            pass

        viewer = Viewer()
        viewer.setupCapture(None)
        viewer.setupRecording(None)
        assert viewer.wantsMoreFrames() is False
        viewer.recorder = object()
        assert viewer.wantsMoreFrames() is True


@windows_only
class TestFinishingAFrame:
    """A pbuffer has nothing to present to, so what ends a frame is a flush --
    the point at which its commands are guaranteed to have reached the driver,
    which is what a readback, a capture or an encode after it depends on."""

    def test_it_flushes(self, monkeypatch):
        import OpenGL.GL as gl

        flushed = []
        monkeypatch.setattr(gl, 'glFlush', lambda: flushed.append(True))
        instance = wglcontext.WGLContext.__new__(wglcontext.WGLContext)
        instance.SwapBuffers()
        assert flushed == [True]


class TestAFailedConstructionSaysWhatIsMissing:
    """The module invites an application to try WGL and fall back, so a failure
    is an expected outcome rather than the end of the process."""

    def test_a_driver_with_no_pbuffers_is_refused_by_name(self, monkeypatch):
        from OpenGL.WGL import offscreen

        monkeypatch.setattr(offscreen, 'available',
                            lambda profile='core': ('WGL_ARB_pbuffer',))
        with pytest.raises(wglcontext.WGLContextError) as caught:
            wglcontext.WGLContext(size=(16, 16))
        assert 'WGL_ARB_pbuffer' in str(caught.value)

    def test_the_failure_is_this_packages_own_class(self, monkeypatch):
        """A caller catches one thing whichever offscreen backend it asked
        for, rather than importing the binding's exception to catch it."""
        from OpenGL.WGL import offscreen

        def refuses(**named):
            raise offscreen.WGLError('nothing doing')

        monkeypatch.setattr(offscreen, 'OffscreenContext', refuses)
        with pytest.raises(wglcontext.WGLContextError):
            wglcontext.WGLContext(size=(16, 16))

    def test_availability_is_answerable_without_creating_anything(self):
        """What lets an application choose between this and a window before
        committing to either."""
        missing = wglcontext.available()
        assert isinstance(missing, tuple)


class TestItIsRegisteredAsABackend:
    """``OPENGLCONTEXT_BACKEND=wgl`` has to reach it, on every platform: the
    registry is what a name is looked up in, and a name absent from it is a
    RuntimeError naming the backends that are there."""

    def test_the_context_is_registered(self):
        from OpenGLContext import plugins

        assert plugins.Context.match('wgl').name == 'wgl'

    def test_the_interactive_slot_is_the_same_class(self):
        """A context nothing can click on has no separate interactive form."""
        from OpenGLContext import plugins

        assert (plugins.InteractiveContext.match('wgl').load()
                is plugins.Context.match('wgl').load())

    def test_the_vrml_context_is_registered(self):
        from OpenGLContext import plugins

        loaded = plugins.VRMLContext.match('wgl').load()
        assert issubclass(loaded, wglcontext.WGLContext)
