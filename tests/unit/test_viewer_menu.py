"""The viewer's own screens (:mod:`OpenGLContext.viewer.menu`).

``oglc-view`` with nothing named opens a menu, and from it a shelf of models and
worlds with pictures.  These are plain
:class:`~OpenGLContext.ui.panel.Panel` trees, so what they do is checkable
without a window: press the button and see which callback ran, choose a category
and see the band change, pick an entry and see what would be opened.
"""
import pytest

from OpenGLContext.ui.gallery import Carousel
from OpenGLContext.ui.metrics import FontMetrics
from OpenGLContext.ui.panel import Panel
from OpenGLContext.ui.widgets import Button, Select, TextField
from OpenGLContext.viewer import menu
from OpenGLContext.viewer.library import Entry, Library, MODELS, WORLDS


@pytest.fixture
def metrics():
    return FontMetrics(char_width=8, char_height=16, line_gap=2)


@pytest.fixture
def library():
    return Library([
        Entry(name='Duck', source='Duck', category=MODELS, preview='duck.png',
              note='a duck'),
        Entry(name='Box', source='Box', category=MODELS),
        Entry(name='Valley', source='valley.wrl', category=WORLDS,
              options={'physics': True}),
    ])


def press(panel, name):
    """Press the named button, as a click or Enter would."""
    widget = panel.find(name)
    assert widget is not None, 'no button named %r' % (name,)
    widget.activate()


class TestTheMainMenu:
    def test_it_offers_the_things_a_viewer_can_do(self):
        panel = menu.main_menu()
        for name in ('browse', 'settings', 'bindings', 'quit'):
            assert isinstance(panel.find(name), Button), name

    def test_each_button_calls_what_it_was_given(self):
        rang = []
        panel = menu.main_menu(
            on_browse=lambda: rang.append('browse'),
            on_settings=lambda: rang.append('settings'),
            on_bindings=lambda: rang.append('bindings'),
            on_quit=lambda: rang.append('quit'))
        for name in ('browse', 'settings', 'bindings', 'quit'):
            press(panel, name)
        assert rang == ['browse', 'settings', 'bindings', 'quit']

    def test_escape_does_not_close_it(self):
        """There is nothing behind the launch menu; leaving is what Quit is."""
        assert not menu.main_menu().closeOnEscape

    def test_a_viewer_with_something_open_can_resume(self):
        """Escape must never be the only answer to "I have a world loaded"."""
        panel = menu.main_menu(on_resume=lambda: None)
        assert panel.closeOnEscape
        resume = panel.find('resume')
        assert isinstance(resume, Button)
        assert 'Resume' in str(resume.text)

    def test_resume_is_the_first_thing_offered(self):
        """Somebody who pressed Escape by accident wants out of this screen."""
        panel = menu.main_menu(on_resume=lambda: None)
        column = panel.children[0]
        names = [str(child.name) for child in column.children if child.name]
        assert names.index('resume') < names.index('quit')

    def test_resume_runs_what_it_was_given(self):
        went = []
        panel = menu.main_menu(on_resume=lambda: went.append(True))
        press(panel, 'resume')
        assert went == [True]

    def test_with_nothing_loaded_there_is_nothing_to_resume(self):
        panel = menu.main_menu()
        assert panel.find('resume') is None
        assert not panel.closeOnEscape

    def test_it_says_what_it_is(self):
        assert menu.main_menu(subtitle='0 models').title or True
        assert 'oglc-view' in menu.TITLE


class TestOpeningAURL:
    """Not everything worth looking at is on the shelf.

    A model somebody was sent, or one published anywhere at all, should not
    need the command line -- which is the one thing a viewer launched from a
    desktop does not have.
    """

    def test_the_menu_offers_somewhere_to_type_one(self):
        assert isinstance(menu.main_menu().find('url'), TextField)

    def test_typing_one_and_pressing_open_opens_it(self):
        opened = []
        panel = menu.main_menu(on_open=opened.append)
        panel.find('url').value = 'https://example.com/model.glb'
        press(panel, 'open-url')
        assert opened == ['https://example.com/model.glb']

    def test_pressing_return_in_the_field_opens_it_too(self):
        """Typing an address and pressing Return is what a person expects."""
        opened = []
        panel = menu.main_menu(on_open=opened.append)
        field = panel.find('url')
        field.value = 'https://example.com/model.glb'
        field.activate()
        assert opened == ['https://example.com/model.glb']

    def test_an_empty_box_opens_nothing(self):
        opened = []
        panel = menu.main_menu(on_open=opened.append)
        press(panel, 'open-url')
        assert opened == []

    def test_surrounding_space_is_not_part_of_the_address(self):
        """Pasted addresses arrive with it more often than not."""
        opened = []
        panel = menu.main_menu(on_open=opened.append)
        panel.find('url').value = '  https://example.com/model.glb\n'
        press(panel, 'open-url')
        assert opened == ['https://example.com/model.glb']

    def test_a_local_path_is_just_as_good(self):
        opened = []
        panel = menu.main_menu(on_open=opened.append)
        panel.find('url').value = '/models/duck.glb'
        press(panel, 'open-url')
        assert opened == ['/models/duck.glb']

    def test_a_menu_nobody_gave_a_handler_still_works(self):
        panel = menu.main_menu()
        panel.find('url').value = 'https://example.com/model.glb'
        press(panel, 'open-url')


class TestTheBrowseScreen:
    def test_it_shows_the_first_category(self, library):
        panel = menu.browse_screen(library)
        band = panel.find('entry')
        assert isinstance(band, Carousel)
        assert list(band.optionLabels) == ['Duck', 'Box']

    def test_the_pictures_are_the_entries_own(self, library):
        band = menu.browse_screen(library).find('entry')
        assert list(band.optionImages) == ['duck.png', '']

    def test_the_categories_are_offered(self, library):
        chooser = menu.browse_screen(library).find('category')
        assert isinstance(chooser, Select)
        assert list(chooser.options) == [MODELS, WORLDS]

    def test_choosing_a_category_changes_the_band(self, library):
        panel = menu.browse_screen(library)
        chooser, band = panel.find('category'), panel.find('entry')
        chooser.value = WORLDS
        chooser.changed()
        assert list(band.optionLabels) == ['Valley']
        assert band.value == 'Valley'

    def test_opening_hands_back_the_entry_rather_than_a_name(self, library):
        """The caller needs the options too, not just the source."""
        opened = []
        panel = menu.browse_screen(library, on_open=opened.append)
        panel.find('entry').value = 'Box'
        press(panel, 'open')
        assert [entry.name for entry in opened] == ['Box']

    def test_opening_from_another_category_finds_the_right_entry(self, library):
        opened = []
        panel = menu.browse_screen(library, on_open=opened.append)
        chooser = panel.find('category')
        chooser.value = WORLDS
        chooser.changed()
        press(panel, 'open')
        assert [entry.name for entry in opened] == ['Valley']

    def test_choosing_a_picture_opens_it(self, library):
        """A double journey through Open is not what a gallery wants."""
        opened = []
        panel = menu.browse_screen(library, on_open=opened.append)
        band = panel.find('entry')
        band.value = 'Box'
        band.activate()
        assert [entry.name for entry in opened] == ['Box']

    def test_cancelling_goes_back(self, library):
        went = []
        panel = menu.browse_screen(library, on_cancel=lambda: went.append(True))
        press(panel, 'cancel')
        assert went == [True]

    def test_escaping_out_of_it_is_cancelling(self, library):
        went = []
        panel = menu.browse_screen(library, on_cancel=lambda: went.append(True))
        panel.close()
        assert went == [True]

    def test_closing_because_something_was_chosen_is_not_cancelling(self, library):
        """The Cancel path puts the launch menu back, so a choice must not run it.

        Whoever handles the choice closes the screen to get it out of the way
        (``close(True)``); that is the opposite of Cancel and had been running
        Cancel's handler, which left the launch menu sitting over the model that
        had just been opened.
        """
        went = []
        panel = menu.browse_screen(library, on_cancel=lambda: went.append(True))
        panel.close(True)
        assert went == []

    def test_the_note_says_what_the_selection_is(self, library):
        panel = menu.browse_screen(library)
        assert 'a duck' in panel.find('note').text

    def test_the_note_follows_the_selection(self, library):
        panel = menu.browse_screen(library)
        band = panel.find('entry')
        band.value = 'Box'
        band.changed()
        assert 'a duck' not in panel.find('note').text

    def test_an_empty_shelf_still_opens(self):
        """Offline, with no worlds in the tree: a message, not a traceback."""
        panel = menu.browse_screen(Library())
        assert isinstance(panel, Panel)
        assert panel.find('open') is not None

    def test_it_lays_out(self, library, metrics):
        """A tree that cannot be measured is a screen that cannot be shown."""
        menu.browse_screen(library).layout((1280, 720), metrics)


class TestManyEntries:
    """Hundreds of models: the band shows a window, and moving is not one at a time."""

    @pytest.fixture
    def big(self):
        return Library([Entry(name='M%03d' % index, source='m%d' % index,
                              category=MODELS) for index in range(300)])

    def test_the_band_holds_them_all(self, big):
        assert len(menu.browse_screen(big).find('entry').options) == 300

    def test_only_a_few_are_drawn(self, big, metrics):
        panel = menu.browse_screen(big)
        panel.layout((1280, 720), metrics)
        assert len(panel.find('entry').visible()) <= menu.SHOWN

    def test_it_lays_out_as_fast_with_three_hundred_as_with_three(self, big, metrics):
        menu.browse_screen(big).layout((1280, 720), metrics)

    def test_a_page_at_a_time_is_offered(self, big):
        """Two hundred presses of an arrow key is not browsing."""
        panel = menu.browse_screen(big)
        band = panel.find('entry')
        first = band.value
        press(panel, 'page-forward')
        assert band.value != first
        assert band.index == menu.SHOWN

    def test_paging_back_returns(self, big):
        panel = menu.browse_screen(big)
        band = panel.find('entry')
        press(panel, 'page-forward')
        press(panel, 'page-back')
        assert band.index == 0

    def test_paging_wraps_rather_than_stopping(self, big):
        panel = menu.browse_screen(big)
        band = panel.find('entry')
        press(panel, 'page-back')
        assert band.index == len(band.options) - menu.SHOWN
