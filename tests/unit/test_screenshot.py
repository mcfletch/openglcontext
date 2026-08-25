"""The screenshot key every context has, and where the picture it takes goes.

A key handler runs *between* frames, and by then the back buffer no longer holds
what the player was looking at -- the driver has recycled it.  So the key asks
for a picture and the frame takes it, at the one moment it is both finished and
still readable: in :meth:`OpenGLContext.context.Context.presentFrame`, before
the swap.  That split is what most of this file is about.
"""
import os
import sys

import pytest

from OpenGLContext import screenshot, userpaths
from OpenGLContext.context import Context


class Recorder(screenshot.ScreenshotMixin):
    """A context stripped to the screenshot machinery and what it calls."""

    setupDefaultEventCallbacks = Context.setupDefaultEventCallbacks
    presentFrame = Context.presentFrame

    def __init__(self):
        self.bound = []
        self.did = []
        self.redraws = 0

    def addEventHandler(self, type, name='', state=None, modifiers=None,
                        function=None, **named):
        self.bound.append({
            'type': type, 'name': name, 'state': state,
            'modifiers': tuple(modifiers) if modifiers else None,
            'function': function,
        })

    def find(self, name):
        return [entry for entry in self.bound if entry['name'] == name]

    def triggerRedraw(self, force=0):
        self.redraws += 1

    def OnSaveImage(self, event=None):
        self.did.append('saved')
        return (640, 480)

    def SwapBuffers(self):
        self.did.append('swapped')

    # -- borrowed only so the default bindings can be registered ----------
    OnEscape = Context.OnEscape
    OnQuit = Context.OnQuit
    OnFrameRate = Context.OnFrameRate
    OnNextViewpoint = Context.OnNextViewpoint


class Definition:
    """Stands in for the ContextDefinition, which is where a title lives."""

    def __init__(self, title=''):
        self.title = title


class Saver(screenshot.ScreenshotMixin):
    """A context stripped to what naming and writing a picture needs."""

    APPLICATION_NAME = 'OpenGLContext'

    def __init__(self, title=''):
        self.contextDefinition = Definition(title)

    def getViewPort(self):
        return (640, 480)

    def getApplicationName(self):
        return self.APPLICATION_NAME


@pytest.fixture
def written(monkeypatch, tmp_path):
    """Saving records the path it would have written, and writes nothing."""
    import numpy as np
    from OpenGLContext import capture

    paths = []
    monkeypatch.setattr(capture, 'ensure_pillow', lambda: True)
    monkeypatch.setattr(capture, 'read_back_buffer',
                        lambda *a, **k: (np.zeros((4, 4, 3), 'B'), 4, 4))
    monkeypatch.setattr(capture, 'save_png',
                        lambda path, pixels: paths.append(path) or True)
    monkeypatch.setattr(userpaths, 'picturesdirectory', lambda: str(tmp_path))
    monkeypatch.setattr(sys, 'argv', ['/opt/venv/bin/oglc-gltf'])
    return paths


@pytest.fixture
def recorder():
    recorder = Recorder()
    recorder.setupDefaultEventCallbacks()
    return recorder


ALT = (False, False, True)


class TestTheKeyIsThereWithoutAsking:
    """Any context at all, with no application configuration."""

    def test_f2_is_bound(self, recorder):
        assert recorder.find('<F2>')

    def test_it_is_a_key_down_and_not_a_character(self, recorder):
        """A function key produces no character, so a keypress never arrives."""
        entry = recorder.find('<F2>')[0]
        assert entry['type'] == 'keyboard'
        assert entry['state'] == 1

    def test_f2_asks_rather_than_saving(self, recorder):
        assert recorder.find('<F2>')[0]['function'].__name__ == 'requestScreenshot'

    def test_alt_s_asks_the_same_way(self, recorder):
        """Alt+S is the demos' key for the same thing, and takes the same route."""
        entry = [item for item in recorder.find('s')
                 if item['modifiers'] == ALT][0]
        assert entry['function'].__name__ == 'requestScreenshot'

    def test_an_application_can_keep_f2_for_itself(self):
        """`screenshotKey = ''` binds none, and nothing else changes."""
        class Quiet(Recorder):
            screenshotKey = ''
        quiet = Quiet()
        quiet.setupDefaultEventCallbacks()
        assert not quiet.find('<F2>')
        assert quiet.find('<escape>')

    def test_an_application_can_move_it(self):
        class Elsewhere(Recorder):
            screenshotKey = '<F12>'
        moved = Elsewhere()
        moved.setupDefaultEventCallbacks()
        assert moved.find('<F12>')


class TestAskingForOne:
    def test_pressing_it_takes_no_picture_yet(self, recorder):
        recorder.requestScreenshot()
        assert recorder.did == []

    def test_it_asks_for_a_frame_to_take_one_of(self, recorder):
        """With nothing moving there is no next frame until something asks."""
        recorder.requestScreenshot()
        assert recorder.redraws == 1

    def test_nothing_pending_takes_nothing(self, recorder):
        assert recorder.takePendingScreenshot() is False
        assert recorder.did == []

    def test_the_frame_takes_the_one_that_was_asked_for(self, recorder):
        recorder.requestScreenshot()
        assert recorder.takePendingScreenshot() is True
        assert recorder.did == ['saved']

    def test_one_press_is_one_picture(self, recorder):
        recorder.requestScreenshot()
        recorder.takePendingScreenshot()
        recorder.takePendingScreenshot()
        assert recorder.did == ['saved']

    def test_a_context_that_never_asks_holds_no_state(self):
        """The flag is a class attribute, so an untouched context reads it."""
        assert screenshot.ScreenshotMixin._screenshotPending is False
        assert '_screenshotPending' not in Recorder().__dict__


class TestTheMomentItIsTaken:
    def test_the_picture_is_read_before_the_buffers_are_swapped(self, recorder):
        """After the swap the back buffer holds an older frame."""
        recorder.requestScreenshot()
        recorder.presentFrame()
        assert recorder.did == ['saved', 'swapped']

    def test_an_ordinary_frame_is_only_swapped(self, recorder):
        recorder.presentFrame()
        assert recorder.did == ['swapped']

    def test_swapbuffers_is_still_the_backend_s_own(self, recorder):
        """An application override of it runs exactly as it always did."""
        recorder.SwapBuffers()
        assert recorder.did == ['swapped']


class TestThePassPresentsTheFrame:
    """Both flat passes hand the finished frame back rather than swapping it."""

    @pytest.mark.parametrize('module', ['OpenGLContext.passes._flat',
                                        'OpenGLContext.passes.flatcompat'])
    def test_it_asks_the_context_to_present(self, module):
        import importlib
        import inspect
        source = inspect.getsource(
            importlib.import_module(module).FlatPass.Render)
        assert 'presentFrame' in source
        assert 'context.SwapBuffers()' not in source

    def test_presenting_takes_the_picture_and_swaps(self, recorder):
        from OpenGLContext.passes._flat import presentFrame
        recorder.requestScreenshot()
        presentFrame(recorder)
        assert recorder.did == ['saved', 'swapped']

    def test_a_context_that_cannot_present_is_still_swapped(self):
        """Anything duck-typed as a context keeps working as it did."""
        from OpenGLContext.passes._flat import presentFrame

        class Older:
            did = None

            def SwapBuffers(self):
                self.did = 'swapped'

        older = Older()
        presentFrame(older)
        assert older.did == 'swapped'


class TestWhatThePictureIsCalled:
    def test_the_window_title_names_it(self, written):
        Saver('GLinting Steel').OnSaveImage()
        assert os.path.basename(written[0]).startswith('GLinting-Steel')

    def test_a_title_a_filename_cannot_hold_is_made_safe(self, written):
        Saver('Twitchy: GLitchy/Bang*Bang?').OnSaveImage()
        name = os.path.basename(written[0])
        assert not set(name) & set('\\/:*?"<>|')
        assert name.startswith('Twitchy-GLitchy-Bang-Bang')

    def test_no_title_names_it_for_the_program(self, written):
        """The name that tells one viewer's shots from another's."""
        Saver().OnSaveImage()
        assert os.path.basename(written[0]).startswith('oglc-gltf')

    def test_an_unusable_argv_falls_back_to_the_application_name(self, written,
                                                                monkeypatch):
        """``python -c`` reports ``-c``, which is not a filename."""
        monkeypatch.setattr(sys, 'argv', ['-c'])
        Saver().OnSaveImage()
        assert os.path.basename(written[0]).startswith('OpenGLContext')

    def test_a_caller_naming_the_program_is_obeyed(self, written):
        """The regression harness names the shot after the script under test."""
        Saver('GLinting Steel').OnSaveImage(script='/src/tests/spinning_cube.py')
        assert os.path.basename(written[0]).startswith('spinning_cube')

    def test_a_context_with_no_definition_still_has_a_name(self, written):
        """A context built without one -- a test harness -- must not fail here."""
        saver = Saver()
        del saver.contextDefinition
        saver.OnSaveImage()
        assert os.path.basename(written[0]).startswith('oglc-gltf')


class TestWhereThePictureGoes:
    def test_it_goes_to_the_user_s_pictures(self, monkeypatch, tmp_path):
        pictures = tmp_path / 'Pictures'
        monkeypatch.setattr(userpaths, 'picturesdirectory', lambda: str(pictures))
        assert Saver().screenshotDirectory() == str(pictures)
        assert pictures.is_dir(), 'the directory a picture goes in is made'

    def test_it_falls_back_to_the_working_directory(self, monkeypatch, tmp_path):
        """A stripped container may have no home to put a picture folder in."""
        def refuse():
            raise OSError('no home')
        monkeypatch.setattr(userpaths, 'picturesdirectory', refuse)
        monkeypatch.chdir(tmp_path)
        assert Saver().screenshotDirectory() == str(tmp_path)

    def test_the_shot_lands_there(self, written, tmp_path):
        Saver('GLinting Steel').OnSaveImage()
        assert os.path.dirname(written[0]) == str(tmp_path)

    def test_it_does_not_write_beside_the_launcher(self, written):
        """argv[0] for a console script is inside the virtualenv's bin."""
        Saver().OnSaveImage()
        assert '/opt/venv/bin' not in written[0]

    def test_a_caller_naming_its_own_file_is_obeyed(self, written, tmp_path):
        """An absolute template goes where it says, picture folder or not."""
        target = str(tmp_path / 'reference-%(count)04i.png')
        Saver().OnSaveImage(template=target, overwrite=True)
        assert written[0] == str(tmp_path / 'reference-0001.png')

    def test_it_does_not_overwrite_an_earlier_shot(self, written):
        saver = Saver('GLinting Steel')
        saver.OnSaveImage()
        open(written[0], 'wb').close()
        saver.OnSaveImage()
        assert written[1] != written[0]


class TestWhenNoPictureCanBeWritten:
    """Each of these answers ``(0, 0)``, which is what a retrying caller reads."""

    @pytest.fixture
    def capture(self, monkeypatch, tmp_path):
        from OpenGLContext import capture

        monkeypatch.setattr(userpaths, 'picturesdirectory', lambda: str(tmp_path))
        monkeypatch.setattr(sys, 'argv', ['/opt/venv/bin/oglc-gltf'])
        return capture

    def test_without_pillow_nothing_is_written(self, capture, monkeypatch):
        """Pillow is what turns the pixels into a file."""
        written = []
        monkeypatch.setattr(capture, 'ensure_pillow', lambda: None)
        monkeypatch.setattr(capture, 'save_png',
                            lambda path, pixels: written.append(path) or True)
        assert Saver().OnSaveImage() == (0, 0)
        assert written == []

    def test_a_window_with_no_size_yet_is_not_read(self, capture, monkeypatch):
        """A context asked for a picture before it has been sized."""
        monkeypatch.setattr(capture, 'ensure_pillow', lambda: True)

        class Unsized(Saver):
            def getViewPort(self):
                return (0, 0)

        assert Unsized().OnSaveImage() == (0, 0)

    def test_a_write_that_fails_says_so(self, capture, monkeypatch):
        import numpy as np

        monkeypatch.setattr(capture, 'ensure_pillow', lambda: True)
        monkeypatch.setattr(capture, 'read_back_buffer',
                            lambda *a, **k: (np.zeros((4, 4, 3), 'B'), 4, 4))
        monkeypatch.setattr(capture, 'save_png', lambda path, pixels: False)
        assert Saver().OnSaveImage() == (0, 0)

    def test_a_template_that_can_only_name_one_file_gives_up(self, capture,
                                                             monkeypatch,
                                                             tmp_path):
        """Without ``%(count)s`` every try is the same name, and it is taken."""
        import numpy as np

        monkeypatch.setattr(capture, 'ensure_pillow', lambda: True)
        monkeypatch.setattr(capture, 'read_back_buffer',
                            lambda *a, **k: (np.zeros((4, 4, 3), 'B'), 4, 4))
        target = tmp_path / 'only.png'
        target.write_bytes(b'')
        assert Saver().OnSaveImage(template=str(target)) == (0, 0)


class TestTheNameIsFilenameSafe:
    @pytest.mark.parametrize('title, expected', [
        ('GLinting Steel', 'GLinting-Steel'),
        ('Twitchy: GLitchy Bang Bang', 'Twitchy-GLitchy-Bang-Bang'),
        ('a/b\\c', 'a-b-c'),
        ('  spaced  out  ', 'spaced-out'),
        ('...', ''),
        ('', ''),
    ])
    def test_it(self, title, expected):
        assert screenshot.filenameSafe(title) == expected
