"""Choosing what a frozen application carries of the engine's optional backends."""

import pytest

from OpenGLContext import packaging


def test_the_kept_backend_is_not_excluded():
    excluded = packaging.unused_backend_modules(keep=['glfw'])
    assert 'glfw' not in excluded


def test_the_other_backends_toolkits_are_excluded():
    excluded = packaging.unused_backend_modules(keep=['glfw'])
    assert 'pygame' in excluded
    assert 'wx' in excluded
    assert 'PySide6' in excluded


def test_nothing_of_the_engine_itself_is_excluded():
    """The context modules are pure Python and cost nothing; the toolkits cost megabytes.

    Excluding an engine module the hook reports as a hidden import would put the
    two in conflict for no saving.
    """
    excluded = packaging.unused_backend_modules(keep=['glfw'])
    assert not [name for name in excluded if name.startswith('OpenGLContext.')]


def test_keeping_several_backends_keeps_each_ones_toolkit():
    excluded = packaging.unused_backend_modules(keep=['glfw', 'pygame'])
    assert 'pygame' not in excluded
    assert 'glfw' not in excluded
    assert 'wx' in excluded


def test_the_result_is_sorted_and_unique():
    excluded = packaging.unused_backend_modules(keep=['glfw'])
    assert excluded == sorted(set(excluded))


def test_an_unknown_backend_is_refused():
    """A typo would otherwise excise the backend the application actually uses."""
    with pytest.raises(ValueError, match='glwf'):
        packaging.unused_backend_modules(keep=['glwf'])


def test_keeping_nothing_is_refused():
    """A frozen application with no windowing backend cannot open a window."""
    with pytest.raises(ValueError):
        packaging.unused_backend_modules(keep=[])


class TestTheLibrariesTheMachineIsAskedFor:
    """A package names what a graphical session does not already imply.

    GLFW opens every windowing library through ``dlopen`` rather than linking
    it, so nothing is discoverable from the binaries: the names come from the
    library itself and are declared here.
    """

    def test_the_rendering_libraries_belong_to_no_session(self):
        """Whichever way the window is opened, these are what draws in it."""
        assert 'libgl1' in packaging.SYSTEM_LIBRARIES
        assert 'libegl1' in packaging.SYSTEM_LIBRARIES
        assert 'libglu1-mesa' in packaging.SYSTEM_LIBRARIES

    def test_no_session_library_is_in_the_common_set(self):
        """Naming X11 unconditionally is what made the first list wrong."""
        common = set(packaging.SYSTEM_LIBRARIES)
        assert not common & set(packaging.X11_LIBRARIES)
        assert not common & set(packaging.WAYLAND_LIBRARIES)

    def test_by_default_a_package_asks_for_whichever_the_machine_has(self):
        """One dependency, satisfied by either stack.

        The session belongs to whoever is playing. A machine logged into X11
        has libX11 already and one logged into Wayland has libwayland-client
        already, so an alternative asks for neither in particular and installs
        without dragging one desktop's libraries onto the other.
        """
        asked = packaging.session_libraries()
        alternative = [name for name in asked if '|' in name]
        assert len(alternative) == 1, asked
        wayland, x11 = [part.strip() for part in alternative[0].split('|')]
        assert wayland == 'libwayland-client0'
        assert x11 == 'libx11-6'

    def test_wayland_is_the_first_alternative(self):
        """apt installs the first one when a machine has neither."""
        alternative = [n for n in packaging.session_libraries('either') if '|' in n][0]
        assert alternative.startswith('libwayland-client0')

    def test_asking_for_either_names_no_stack_in_full(self):
        asked = set(packaging.session_libraries('either'))
        assert not asked & set(packaging.X11_LIBRARIES)
        assert not asked & set(packaging.WAYLAND_LIBRARIES)

    def test_a_package_pinned_to_wayland_asks_for_the_wayland_libraries(self):
        """For a controlled fleet, where the session is known."""
        asked = packaging.session_libraries('wayland')
        assert 'libwayland-client0' in asked
        assert 'libxkbcommon0' in asked
        assert 'libdecor-0-0' in asked, 'GLFW draws its own decorations through it'
        assert 'libx11-6' not in asked

    def test_a_package_pinned_to_x11_asks_for_the_x11_libraries(self):
        asked = packaging.session_libraries('x11')
        assert 'libx11-6' in asked
        assert 'libxrandr2' in asked
        assert 'libwayland-client0' not in asked

    def test_asking_for_both_asks_for_everything(self):
        asked = set(packaging.session_libraries('both'))
        assert set(packaging.X11_LIBRARIES) <= asked
        assert set(packaging.WAYLAND_LIBRARIES) <= asked

    def test_the_rendering_libraries_come_with_every_choice(self):
        for session in packaging.SESSIONS:
            assert set(packaging.SYSTEM_LIBRARIES) <= set(
                packaging.session_libraries(session)), session

    def test_the_answer_is_sorted_and_unique(self):
        for session in packaging.SESSIONS:
            asked = packaging.session_libraries(session)
            assert asked == sorted(set(asked)), session

    def test_a_session_nobody_runs_is_refused(self):
        """Better than a package that quietly asks for nothing."""
        with pytest.raises(ValueError, match='mir'):
            packaging.session_libraries('mir')

    def test_a_titlebar_is_recommended_wherever_wayland_is_possible(self):
        """libdecor finds no plug-in and the window comes up undecorated.

        A game with no way to move or close its window is the kind of thing a
        player blames the game for, and either plug-in fixes it. It is a
        recommendation rather than a requirement: without it the game runs, and
        a full-screen game never wanted a titlebar anyway.
        """
        for session in ('either', 'wayland', 'both'):
            recommended = packaging.session_recommendations(session)
            asked = packaging.session_libraries(session) + recommended
            assert any('libdecor-0-plugin' in name for name in recommended), session
            assert 'libdecor-0-0' in asked, session

    def test_a_package_pinned_to_x11_recommends_nothing_it_does_not_need(self):
        """X11 decorations are the window manager's job, and libdecor pulls GTK."""
        assert packaging.session_recommendations('x11') == []

    def test_nothing_is_both_required_and_recommended(self):
        """A package that recommends what it depends on contradicts itself."""
        for session in packaging.SESSIONS:
            required = set(packaging.session_libraries(session))
            recommended = set(packaging.session_recommendations(session))
            assert not required & recommended, session
