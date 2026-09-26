"""Which window system a context opens on, and how that is said.

A context holds a window system rather than deriving from one, and which one it
holds is a field of its definition: ``ContextDefinition.windowsystem``.  An
empty field is settled when the context is built -- from
``OPENGLCONTEXT_BACKEND``, then the user's ``defaultcontext.txt`` preference,
then the first registered window system that imports, GLFW first -- and
``'offscreen'`` names whichever renders with no window on this platform.

:func:`OpenGLContext.windowsystem.choose` is the rule, and takes everything it
reads as an argument, so every branch is checked here with no GL, no toolkit and
no environment.
"""
import pytest

from OpenGLContext import plugins, windowsystem
from OpenGLContext.context import Context
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.windowsystem import WindowSystemUnavailable, choose

#: What every choice below is made among, in registration order.
REGISTERED = ('pygame', 'wx', 'glut', 'glfw', 'tk', 'egl', 'wgl')


def importable(*names):
    """A probe under which exactly ``names`` import."""
    def probe(name):
        if name in names:
            return None
        return ImportError('No module named %r' % (name,))
    return probe


EVERYTHING = importable(*REGISTERED)


class TestAnEmptyRequest:
    def test_the_environment_wins(self):
        assert choose('', environment='glut', preference='tk',
                      registered=REGISTERED, probe=EVERYTHING) == 'glut'

    def test_then_the_users_preference(self):
        assert choose('', environment=None, preference='tk',
                      registered=REGISTERED, probe=EVERYTHING) == 'tk'

    def test_then_glfw_where_it_imports(self):
        assert choose('', registered=REGISTERED, probe=EVERYTHING) == 'glfw'

    def test_then_the_next_window_system_in_platform_order(self):
        assert choose('', registered=REGISTERED,
                      probe=importable('pygame', 'tk', 'glut')) == 'glut'

    def test_an_offscreen_system_is_never_the_fallback(self):
        """A program that asked for nothing is asking for a window; a context
        that renders one frame and exits is not one."""
        with pytest.raises(WindowSystemUnavailable, match='egl'):
            choose('', registered=REGISTERED, probe=importable('egl', 'wgl'))

    def test_a_system_outside_the_platform_order_is_still_found(self):
        """A third party's window system registered through an entry point
        is a window like any other."""
        assert choose('', registered=REGISTERED + ('sdl3',),
                      probe=importable('sdl3')) == 'sdl3'

    def test_a_preference_that_will_not_import_gives_way(self, caplog):
        """A stale ``defaultcontext.txt`` must not stop every program on the
        machine from opening a window; it is reported and passed over."""
        chosen = choose('', preference='wx', registered=REGISTERED,
                        probe=importable('glfw'))
        assert chosen == 'glfw'
        assert 'wx' in caplog.text

    def test_an_environment_that_will_not_import_is_an_error(self):
        """The variable is set for this run, and a run that asked for one
        toolkit and silently got another has measured the wrong thing."""
        with pytest.raises(WindowSystemUnavailable, match='wx'):
            choose('', environment='wx', registered=REGISTERED,
                   probe=importable('glfw'))


class TestANamedRequest:
    def test_the_name_is_taken(self):
        assert choose('pygame', environment='glut', preference='tk',
                      registered=REGISTERED, probe=EVERYTHING) == 'pygame'

    def test_an_unregistered_name_says_what_is_registered(self):
        with pytest.raises(WindowSystemUnavailable) as raised:
            choose('no-such-toolkit', registered=REGISTERED, probe=EVERYTHING)
        message = str(raised.value)
        assert 'no-such-toolkit' in message
        assert 'glfw' in message and 'pygame' in message

    def test_a_name_that_will_not_import_carries_the_import_error(self):
        with pytest.raises(WindowSystemUnavailable) as raised:
            choose('wx', registered=REGISTERED, probe=importable('glfw'))
        assert "No module named 'wx'" in str(raised.value)


class TestOffscreen:
    @pytest.mark.parametrize('platform', ['win32', 'cygwin'])
    def test_windows_renders_on_a_pbuffer(self, platform):
        assert choose('offscreen', platform=platform, registered=REGISTERED,
                      probe=EVERYTHING) == 'wgl'

    @pytest.mark.parametrize('platform', ['linux', 'freebsd14', 'darwin'])
    def test_everywhere_else_renders_on_egl(self, platform):
        assert choose('offscreen', platform=platform, registered=REGISTERED,
                      probe=EVERYTHING) == 'egl'

    def test_the_environment_can_ask_for_it(self):
        assert choose('', environment='offscreen', platform='linux',
                      registered=REGISTERED, probe=EVERYTHING) == 'egl'

    def test_offscreen_with_nothing_behind_it_is_an_error(self):
        with pytest.raises(WindowSystemUnavailable, match='egl'):
            choose('offscreen', platform='linux', registered=REGISTERED,
                   probe=importable('glfw'))


class TestTheRegistry:
    def test_the_engines_window_systems_are_registered(self):
        names = windowsystem.registered()
        for name in ('glfw', 'glut', 'pygame', 'tk', 'wx', 'egl', 'wgl'):
            assert name in names

    def test_glfw_loads_as_a_window_system_class(self):
        loaded = windowsystem.load('glfw')
        assert issubclass(loaded, windowsystem.WindowSystem)
        assert loaded.name == 'glfw'

    def test_an_unregistered_name_raises_on_load(self):
        with pytest.raises(WindowSystemUnavailable, match='no-such-toolkit'):
            windowsystem.load('no-such-toolkit')

    def test_a_registered_system_that_will_not_import_raises_on_load(self):
        plugins.WindowSystem('brokensystem', 'no_such_module_at_all.Nothing')
        try:
            with pytest.raises(WindowSystemUnavailable, match='no_such_module_at_all'):
                windowsystem.load('brokensystem')
        finally:
            plugins.WindowSystem.registry[:] = [
                plugin for plugin in plugins.WindowSystem.registry
                if plugin.name != 'brokensystem'
            ]

    def test_an_entry_point_registers_a_window_system(self, monkeypatch):
        """A package outside the engine names its window system in its own
        metadata; nothing has to import it for the name to be known."""
        from importlib import metadata

        found = metadata.EntryPoint(
            name='thirdparty', value='thirdparty_ws.windowing:ThirdParty',
            group=windowsystem.ENTRY_POINT_GROUP)
        monkeypatch.setattr(plugins, '_entryPoints',
                            lambda group: (found,) if group == found.group else ())
        monkeypatch.setattr(plugins, '_DISCOVERED', set())
        try:
            assert 'thirdparty' in windowsystem.registered()
            plugin = plugins.WindowSystem.by_name('thirdparty')
            assert plugin.import_path == 'thirdparty_ws.windowing.ThirdParty'
        finally:
            plugins.WindowSystem.registry[:] = [
                plugin for plugin in plugins.WindowSystem.registry
                if plugin.name != 'thirdparty'
            ]


class TestTheDefinitionField:
    def test_it_is_empty_unless_set(self):
        assert ContextDefinition().windowsystem == ''

    def test_it_is_not_a_runtime_setting(self):
        """Read once, as the context is built; a settings screen that offered
        it would be offering a switch that does nothing."""
        assert 'windowsystem' not in ContextDefinition.UI_HINTS


class Pinned(Context):
    windowSystemName = 'egl'


class DeclaresOne(Context):
    contextDefinition = ContextDefinition(windowsystem='glut')


class PinnedOverDeclared(Context):
    windowSystemName = 'egl'
    contextDefinition = ContextDefinition(windowsystem='glut', title='declared')


class TestTheClassPinsItsWindowSystem:
    """Precedence: a definition passed in that sets the field, the class's
    ``windowSystemName``, the class's declared definition, the default."""

    def test_nothing_said_leaves_it_to_the_default(self):
        assert Context.resolveDefinition().windowsystem == ''

    def test_the_class_name_is_applied(self):
        assert Pinned.resolveDefinition().windowsystem == 'egl'

    def test_a_declared_definition_is_read(self):
        assert DeclaresOne.resolveDefinition().windowsystem == 'glut'

    def test_the_class_name_outranks_the_declared_definition(self):
        resolved = PinnedOverDeclared.resolveDefinition()
        assert resolved.windowsystem == 'egl'
        assert resolved.title == 'declared'

    def test_a_passed_definition_that_sets_it_wins(self):
        passed = ContextDefinition(windowsystem='tk')
        assert Pinned.resolveDefinition(passed).windowsystem == 'tk'

    def test_a_passed_definition_that_does_not_set_it_takes_the_class_name(self):
        passed = ContextDefinition(title='passed')
        resolved = Pinned.resolveDefinition(passed)
        assert resolved.windowsystem == 'egl'
        assert resolved.title == 'passed'

    def test_a_named_field_wins(self):
        assert Pinned.resolveDefinition(windowsystem='tk').windowsystem == 'tk'
