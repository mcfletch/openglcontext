"""The process environment, read and written through renderoptions.

Every read of an environment variable in the engine goes through
:mod:`OpenGLContext.renderoptions`, and a program that pins one before it opens
a context writes it there too, so that a write after the engine has settled a
variable's answer is not silently ignored.
"""
import pytest

from OpenGLContext import renderoptions

NAME = 'OPENGLCONTEXT_TEST_ENVIRONMENT_READER'


@pytest.fixture(autouse=True)
def _forget(monkeypatch):
    monkeypatch.delenv(NAME, raising=False)
    renderoptions.reset_env_cache()
    yield
    renderoptions.reset_env_cache()


class TestText:
    def test_an_unset_variable_is_the_default(self):
        assert renderoptions.env_text(NAME) == ''
        assert renderoptions.env_text(NAME, 'fallback') == 'fallback'

    def test_an_empty_one_is_the_default_too(self, monkeypatch):
        monkeypatch.setenv(NAME, '   ')
        assert renderoptions.env_text(NAME, 'fallback') == 'fallback'

    def test_a_value_is_read_stripped(self, monkeypatch):
        monkeypatch.setenv(NAME, '  /tmp/session.jsonl \n')
        assert renderoptions.env_text(NAME) == '/tmp/session.jsonl'

    def test_read_once_it_stays_what_it_was(self, monkeypatch):
        monkeypatch.setenv(NAME, 'first')
        assert renderoptions.env_text_once(NAME) == 'first'
        monkeypatch.setenv(NAME, 'second')
        assert renderoptions.env_text_once(NAME) == 'first'
        assert renderoptions.env_text(NAME) == 'second'


class TestWriting:
    def test_setting_one_reaches_the_process_and_its_children(self, monkeypatch):
        monkeypatch.setenv(NAME, 'unset below')
        renderoptions.set_env(NAME, 'pinned')
        assert renderoptions.environment()[NAME] == 'pinned'

    def test_setting_one_already_read_once_is_read_again(self, monkeypatch):
        monkeypatch.setenv(NAME, 'first')
        assert renderoptions.env_text_once(NAME) == 'first'
        renderoptions.set_env(NAME, 'second')
        assert renderoptions.env_text_once(NAME) == 'second'

    def test_a_default_leaves_a_value_already_there(self, monkeypatch):
        monkeypatch.setenv(NAME, 'the shell said')
        renderoptions.default_env(NAME, 'the program says')
        assert renderoptions.env_text(NAME) == 'the shell said'

    def test_a_default_fills_an_unset_one(self, monkeypatch):
        monkeypatch.setenv(NAME, 'placeholder')
        monkeypatch.delenv(NAME)
        renderoptions.default_env(NAME, 'the program says')
        assert renderoptions.env_text_once(NAME) == 'the program says'


class TestTheWholeEnvironment:
    def test_it_cannot_be_written_through(self):
        with pytest.raises(TypeError):
            renderoptions.environment()[NAME] = 'x'

    def test_the_rendering_settings_are_those_that_are_set(self, monkeypatch):
        for name in renderoptions.ENVIRONMENT:
            monkeypatch.delenv(name, raising=False)
        monkeypatch.setenv('OPENGLCONTEXT_SHADOWS', '0')
        monkeypatch.setenv('HOME', '/home/somebody')
        assert renderoptions.rendering_settings() == {'OPENGLCONTEXT_SHADOWS': '0'}
