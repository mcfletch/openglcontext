"""What the GLFW backend calls each key.

A binding names a key once and expects it to work whichever backend the
application opened its window with, so every backend produces the vocabulary
:meth:`~OpenGLContext.events.keyboardevents.KeyboardEventManager.registerCallback`
documents.  GLFW is the default backend, so a key it cannot name is a key most
applications cannot bind.
"""

import pytest

glfw = pytest.importorskip('glfw')

from OpenGLContext.events import glfwevents                # noqa: E402


class Window(object):
    """Enough of a context for a keyboard event; it reads no window at all."""


def name_of(key):
    """The event name GLFW's key code produces, as the event class builds it."""
    return glfwevents.GLFWKeyboardEvent(Window(), key).name


class TestTheNumericKeypad:
    """The keypad is its own set of keys: ``#0``, and the operators as
    characters, which is how the Tk and wx tables spell them."""

    @pytest.mark.parametrize('digit', range(10))
    def test_a_digit_is_hashed(self, digit):
        assert name_of(getattr(glfw, 'KEY_KP_%d' % (digit,))) == '#%d' % (digit,)

    @pytest.mark.parametrize('key,expected', [
        ('KEY_KP_DIVIDE', '/'),
        ('KEY_KP_MULTIPLY', '*'),
        ('KEY_KP_SUBTRACT', '-'),
        ('KEY_KP_ADD', '+'),
        ('KEY_KP_DECIMAL', '.'),
    ])
    def test_an_operator_is_the_character_it_produces(self, key, expected):
        assert name_of(getattr(glfw, key)) == expected

    def test_its_enter_is_the_return_key(self):
        assert name_of(glfw.KEY_KP_ENTER) == '<return>'


class TestTheRestOfTheVocabulary:
    @pytest.mark.parametrize('key,expected', [
        ('KEY_PAUSE', '<pause>'),
        ('KEY_LEFT_SUPER', '<start>'),
        ('KEY_RIGHT_SUPER', '<start>'),
        ('KEY_SPACE', ' '),
        ('KEY_F2', '<F2>'),
        ('KEY_ESCAPE', '<escape>'),
        ('KEY_LEFT_SHIFT', '<shift>'),
    ])
    def test_it_is_named_as_the_other_backends_name_it(self, key, expected):
        assert name_of(getattr(glfw, key)) == expected


def test_a_key_with_no_name_is_told_apart_from_the_next_one():
    """The fallback still has to be distinct, or one binding catches them all."""
    assert name_of(glfw.KEY_F25) != name_of(glfw.KEY_WORLD_1)
