"""What the Pygame backend calls each key.

A binding names a key once -- ``addEventHandler('keyboard', name='<F2>', ...)``
-- and expects it to work whichever backend the application opened its window
with, so every backend has to produce the vocabulary
:meth:`~OpenGLContext.events.keyboardevents.KeyboardEventManager.registerCallback`
documents.  SDL names its keys differently from X11, Tk and wx, and this is the
translation between the two.
"""

import pytest

pygame = pytest.importorskip('pygame')

from OpenGLContext.events.pygameevents import PygameXEvent   # noqa: E402


@pytest.fixture
def translate():
    return PygameXEvent()._translateKey


FUNCTION_KEYS = ['f1', 'f2', 'f5', 'f9', 'f10', 'f12', 'f15']


class TestTheFunctionKeys:
    """``<F2>`` is the screenshot key every context binds."""

    @pytest.mark.parametrize('name', FUNCTION_KEYS)
    def test_they_are_named_in_upper_case(self, translate, name):
        assert translate(name) == '<%s>' % (name.upper(),)

    def test_the_screenshot_key_is_the_one_that_is_bound(self, translate):
        from OpenGLContext.screenshot import ScreenshotMixin
        assert translate(pygame.key.name(pygame.K_F2)) == \
            ScreenshotMixin.screenshotKey


class TestTheKeysNamedAsCharacters:
    def test_space_is_a_space(self, translate):
        assert translate(pygame.key.name(pygame.K_SPACE)) == ' '

    def test_a_letter_is_itself(self, translate):
        assert translate(pygame.key.name(pygame.K_a)) == 'a'

    def test_punctuation_is_itself(self, translate):
        assert translate(pygame.key.name(pygame.K_MINUS)) == '-'


class TestTheNumericKeypad:
    """Pygame brackets the keypad; the rest of OpenGLContext prefixes a hash."""

    @pytest.mark.parametrize('digit', ['0', '5', '9'])
    def test_a_digit_is_hashed(self, translate, digit):
        assert translate('[%s]' % (digit,)) == '#%s' % (digit,)

    @pytest.mark.parametrize('character', ['/', '*', '-', '+', '.'])
    def test_an_operator_is_the_character_it_produces(self, translate,
                                                      character):
        assert translate('[%s]' % (character,)) == character

    def test_its_enter_is_the_return_key(self, translate):
        assert translate(pygame.key.name(pygame.K_KP_ENTER)) == '<return>'


class TestTheKeysThatComeInPairs:
    """A binding asks for shift, not for the left one."""

    @pytest.mark.parametrize('key,expected', [
        ('K_LSHIFT', '<shift>'), ('K_RSHIFT', '<shift>'),
        ('K_LCTRL', '<ctrl>'), ('K_RCTRL', '<ctrl>'),
        ('K_LALT', '<alt>'), ('K_RALT', '<alt>'),
    ])
    def test_both_sides_are_one_name(self, translate, key, expected):
        assert translate(pygame.key.name(getattr(pygame, key))) == expected

    def test_the_arrow_keys_keep_their_own_names(self, translate):
        assert translate(pygame.key.name(pygame.K_LEFT)) == '<left>'
        assert translate(pygame.key.name(pygame.K_RIGHT)) == '<right>'


class TestTheRestOfTheVocabulary:
    @pytest.mark.parametrize('key,expected', [
        ('K_ESCAPE', '<escape>'),
        ('K_RETURN', '<return>'),
        ('K_TAB', '<tab>'),
        ('K_BACKSPACE', '<backspace>'),
        ('K_DELETE', '<delete>'),
        ('K_INSERT', '<insert>'),
        ('K_HOME', '<home>'),
        ('K_END', '<end>'),
        ('K_PAGEUP', '<pageup>'),
        ('K_PAGEDOWN', '<pagedown>'),
        ('K_UP', '<up>'),
        ('K_DOWN', '<down>'),
        ('K_CAPSLOCK', '<capslock>'),
        ('K_NUMLOCK', '<numlock>'),
        ('K_SCROLLOCK', '<scroll>'),
        ('K_PAUSE', '<pause>'),
        ('K_LMETA', '<start>'),
    ])
    def test_it_is_named_as_the_other_backends_name_it(self, translate, key,
                                                       expected):
        assert translate(pygame.key.name(getattr(pygame, key))) == expected


def test_a_synthetic_release_is_named_the_same_way():
    """The release focus loss never delivered has to match its press.

    ``clearHeldKeys`` sends it, so a key held as the window lost focus must
    come back with the name its press carried or nothing can let go of it.
    """
    from OpenGLContext.events import pygameevents
    sent = []

    class Host(pygameevents.EventHandlerMixin):
        def ProcessEvent(self, event):
            sent.append(event)

    host = Host()
    host.emitKey(pygame.K_F2, 0, (0, 0, 0))
    assert [event.name for event in sent] == ['<F2>']
