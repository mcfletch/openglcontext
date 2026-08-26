"""Where a context's definition comes from, whichever backend opens the window.

A program says what kind of context it needs by declaring one on its class::

    class TestContext(BaseContext):
        contextDefinition = ContextDefinition(profile='compatibility')

Twenty-odd tutorials in ``tests/`` say exactly that, because they draw with the
fixed-function pipeline.  The declaration has to reach the window *before* it is
created, which means each backend has to consult it in ``__init__`` rather than
leaving it to :meth:`Context.setDefinition`, which the base class runs after the
window already exists.

The resolution itself lives in one place so the backends cannot disagree about
it: what a caller passed wins, then what the class declared, then a fresh
definition built from the environment.
"""
import pytest

from OpenGLContext.context import Context
from OpenGLContext.contextdefinition import ContextDefinition


class Declared(Context):
    contextDefinition = ContextDefinition(profile='compatibility', title='declared')


class Undeclared(Context):
    pass


def test_an_argument_wins_over_a_declaration():
    passed = ContextDefinition(profile='core')
    assert Declared.resolveDefinition(passed) is passed


def test_the_class_declaration_is_used_when_nothing_is_passed():
    resolved = Declared.resolveDefinition()
    assert resolved.profile == 'compatibility'
    assert resolved.title == 'declared'


def test_the_declaration_is_not_the_node_the_class_holds():
    """Every context gets its own, since a context writes its size back to it."""
    first = Declared.resolveDefinition()
    second = Declared.resolveDefinition()
    assert first is not second
    assert first is not Declared.contextDefinition
    first.size = (640, 480)
    assert tuple(Declared.contextDefinition.size) != (640, 480)


def test_a_class_declaring_nothing_gets_a_fresh_definition(monkeypatch):
    monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
    assert Undeclared.resolveDefinition().profile == 'core'


def test_the_environment_still_reaches_a_field_the_declaration_left_alone(monkeypatch):
    """Copying the declaration must not freeze the defaults it never set."""
    monkeypatch.setenv('OPENGLCONTEXT_MAXIMUM_LIGHTS', '3')
    assert Declared.resolveDefinition().maximumLights == 3


def test_keywords_become_fields_of_a_fresh_definition():
    assert tuple(Undeclared.resolveDefinition(size=(64, 64)).size) == (64, 64)


def test_keywords_are_applied_over_a_declaration():
    assert Declared.resolveDefinition(title='overridden').title == 'overridden'


def test_a_mapping_is_read_as_the_fields_to_set():
    resolved = Undeclared.resolveDefinition({'profile': 'compatibility'})
    assert isinstance(resolved, ContextDefinition)
    assert resolved.profile == 'compatibility'


@pytest.mark.parametrize('module_name, class_name', [
    ('OpenGLContext.glfwcontext', 'GLFWContext'),
    ('OpenGLContext.glutcontext', 'GLUTContext'),
    ('OpenGLContext.pygamecontext', 'PygameContext'),
    ('OpenGLContext.wxcontext', 'wxContext'),
])
def test_every_backend_resolves_the_definition_the_same_way(module_name, class_name):
    """The window is made from the resolved definition, not one built locally."""
    import inspect
    module = pytest.importorskip(module_name)
    source = inspect.getsource(getattr(module, class_name).__init__)
    assert 'resolveDefinition' in source, (
        '%s builds its own definition instead of resolving the declared one'
        % (class_name,))


class TestVersionFollowsTheProfileItWasAskedFor:
    """``version`` defaults from the profile, and must read the one it is with.

    Unset, the field's default is (3,3) for a core profile and (0,0) -- let the
    driver choose -- otherwise.  It cannot see the node it is a field of, so it
    reads the profile the *environment* names; a definition that asks for
    compatibility while ``OPENGLCONTEXT_PROFILE=core`` would then carry a
    version chosen for the other profile, and a backend that turns
    ``version >= 3`` into a context hint opens a 3.3 window for it.
    """

    def test_a_declared_compatibility_profile_does_not_inherit_a_core_version(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
        definition = ContextDefinition(profile='compatibility')
        assert tuple(definition.version) == (0, 0)

    def test_a_declared_core_profile_gets_the_version_core_needs(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'compatibility')
        definition = ContextDefinition(profile='core')
        assert tuple(definition.version) == (3, 3)

    def test_an_explicit_version_is_left_alone(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
        definition = ContextDefinition(profile='compatibility', version=(4, 1))
        assert tuple(definition.version) == (4, 1)

    def test_naming_neither_still_follows_the_environment(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
        assert tuple(ContextDefinition().version) == (3, 3)


class TestTheProfileShorthand:
    """One line for the common case, without replacing a whole definition.

    A demo that draws with the fixed-function pipeline has one thing to say,
    and saying it as a whole :class:`ContextDefinition` costs an import and
    discards whatever definition its base class declared.  ``profile`` on the
    class says the one thing and leaves the rest alone.
    """

    class Legacy(Context):
        profile = 'compatibility'

    class Sized(Context):
        contextDefinition = ContextDefinition(size=(640, 480))
        profile = 'compatibility'

    def test_the_class_attribute_settles_the_profile(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
        assert self.Legacy.resolveDefinition().profile == 'compatibility'

    def test_it_brings_the_version_that_profile_needs(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
        assert tuple(self.Legacy.resolveDefinition().version) == (0, 0)

    def test_it_composes_with_a_declared_definition(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
        resolved = self.Sized.resolveDefinition()
        assert resolved.profile == 'compatibility'
        assert tuple(resolved.size) == (640, 480)

    def test_a_definition_that_names_a_profile_itself_wins(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'compatibility')

        class Explicit(Context):
            profile = 'compatibility'
            contextDefinition = ContextDefinition(profile='core')
        assert Explicit.resolveDefinition().profile == 'core'

    def test_a_passed_definition_is_not_overridden(self):
        passed = ContextDefinition(profile='core')
        assert self.Legacy.resolveDefinition(passed).profile == 'core'

    def test_a_class_saying_nothing_still_follows_the_environment(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_PROFILE', 'core')
        assert Undeclared.resolveDefinition().profile == 'core'
