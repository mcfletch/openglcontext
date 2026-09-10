"""``Context.fromConfig`` builds a Context subclass from a config file
(:meth:`OpenGLContext.context.Context.fromConfig`).

``oglc-test -c settings.ini script.py`` is what reaches it: the file names the
backend to open the window with and the context flavour to open, and the
class that comes back is subclassed by the runner to add its frame counting.
So the result has to be a class -- something usable as a base -- carrying the
``contextDefinition`` the same file configures.

``[context] type`` takes one of the plugin type keys (``context``,
``interactive``, ``vrml``) and defaults to ``vrml``; ``[context] gui`` names a
backend and defaults to whatever the user's preference resolves to.  The rest
of the file is read by
:meth:`OpenGLContext.contextdefinition.ContextDefinition.fromConfig`.
"""
import configparser

import pytest

from OpenGLContext import context
from OpenGLContext.contextdefinition import ContextDefinition


def _config(**options):
    cfg = configparser.ConfigParser()
    cfg.add_section('context')
    for key, value in options.items():
        cfg.set('context', key, value)
    return cfg


class TestItProducesAClass:
    """The runner subclasses the result, so it has to be a class."""

    @pytest.mark.parametrize('type_key', [None, 'context', 'interactive', 'vrml'])
    def test_the_result_can_be_subclassed(self, type_key):
        options = {'gui': 'glfw'}
        if type_key is not None:
            options['type'] = type_key
        found = context.Context.fromConfig(_config(**options))
        assert isinstance(found, type), found

        class Subclass(found):
            pass

        assert issubclass(Subclass, found)

    def test_it_derives_from_the_backend_class(self):
        cfg = _config(gui='glfw', type='vrml')
        found = context.Context.fromConfig(cfg)
        assert issubclass(found, context.Context)


class TestItCarriesTheDefinition:
    """The same file configures the window, and the class holds that.

    The window's own fields come from a ``[contextdefinition]`` section, which
    is what ``ContextDefinition.fromConfig`` reads.
    """

    def test_the_definition_comes_from_the_file(self):
        cfg = _config(gui='glfw', type='vrml')
        cfg.add_section('contextdefinition')
        cfg.set('contextdefinition', 'title', 'A Configured Window')
        found = context.Context.fromConfig(cfg)
        assert isinstance(found.contextDefinition, ContextDefinition)
        assert found.contextDefinition.title == 'A Configured Window'


class TestAnUnknownTypeIsReported:
    """A misspelled type key is a mistake in the file, and is said so."""

    def test_it_names_the_keys_it_accepts(self):
        with pytest.raises(ValueError) as caught:
            context.Context.fromConfig(_config(gui='glfw', type='not-a-type'))
        message = str(caught.value)
        assert 'not-a-type' in message
        for key in ('context', 'interactive', 'vrml'):
            assert key in message, message


class TestAnUnavailableBackendIsNothing:
    """``oglc-test`` falls back when the named backend cannot be loaded."""

    def test_it_gives_none(self):
        assert context.Context.fromConfig(
            _config(gui='no-such-backend', type='vrml')
        ) is None
