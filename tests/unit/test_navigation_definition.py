"""How a context is moved through and looked at, declared on its definition.

``ContextDefinition.navigation`` holds a
:class:`~OpenGLContext.move.navigationdefinition.Navigation` node: the movement
modes in use (registered by name), the views and their arrangements, and for
each whether the user may switch it.  The declarations and the registries are
plain objects, so everything here runs with no GL and no window.
"""
import pytest
from vrml import node as vrmlnode

from OpenGLContext import plugins
from OpenGLContext.contextdefinition import ContextDefinition
from OpenGLContext.move import navigationdefinition as nd
from OpenGLContext.move.modes import (
    ExamineMode, FlyMode, FPSMode, MovementMode, SwimMode, WalkMode,
    FLY_SPEED, WALK_SPEED,
)
from OpenGLContext.multiview.navigation import ViewNavigationMode


class TestTheMovementModeRegistry:
    @pytest.mark.parametrize('name, kind', [
        ('walk', WalkMode), ('fly', FlyMode), ('swim', SwimMode),
        ('fps', FPSMode), ('examine', ExamineMode),
    ])
    def test_the_engine_registers_its_modes(self, name, kind):
        mode = nd.movementMode(name)
        assert isinstance(mode, kind)
        assert mode.name == name

    def test_each_request_makes_a_mode_of_its_own(self):
        """A mode carries a player's rebound keys and tuned speeds; two
        contexts asking for 'walk' must not share one."""
        assert nd.movementMode('walk') is not nd.movementMode('walk')

    def test_a_scale_sizes_the_speeds(self):
        mode = nd.movementMode('fly', scale=10.0)
        assert mode.flySpeed == pytest.approx(FLY_SPEED * 10.0)

    def test_an_unknown_name_says_what_is_registered(self):
        with pytest.raises(KeyError) as raised:
            nd.movementMode('no-such-mode')
        message = str(raised.value)
        assert 'no-such-mode' in message and 'walk' in message

    def test_a_game_registers_its_own(self, monkeypatch):
        plugins.MovementMode('fps-map', 'tests.unit.test_navigation_definition._mapMode')
        try:
            mode = nd.movementMode('fps-map')
            assert isinstance(mode, FlyMode) and mode.name == 'fps-map'
            assert 'fps-map' in nd.registeredModes()
        finally:
            plugins.MovementMode.registry[:] = [
                plugin for plugin in plugins.MovementMode.registry
                if plugin.name != 'fps-map']


def _mapMode(scale=1.0):
    """A game's own mode, as a factory registered by dotted path."""
    return FlyMode(name='fps-map', flySpeed=2.0 * scale)


class TestTheViewGestureRegistry:
    @pytest.mark.parametrize('name', ['plan', 'examine'])
    def test_the_engine_registers_its_gestures(self, name):
        gestures = nd.viewGestures(name)
        assert isinstance(gestures, ViewNavigationMode)
        assert gestures.name == name

    def test_an_unknown_name_says_what_is_registered(self):
        with pytest.raises(KeyError, match='plan'):
            nd.viewGestures('no-such-gesture')


class TestANavigation:
    def test_names_become_the_registered_modes(self):
        navigation = nd.Navigation(modes=['walk', 'fly'])
        assert [type(mode) for mode in navigation.modes] == [WalkMode, FlyMode]

    def test_nodes_are_taken_as_they_are(self):
        walking = WalkMode(name='stroll', walkSpeed=1.0)
        navigation = nd.Navigation(modes=[walking, 'fly'])
        assert navigation.modes[0] is walking
        assert isinstance(navigation.modes[1], FlyMode)

    def test_switching_names_a_known_way(self):
        with pytest.raises(ValueError, match='keys'):
            nd.Navigation(modes=['walk'], modeSwitching=['telepathy'])

    def test_scaled_is_a_copy_with_the_speeds_scaled(self):
        navigation = nd.Navigation(modes=['walk', 'examine'], modeSwitching=['keys'])
        scaled = navigation.scaled(4.0)
        assert scaled is not navigation
        assert scaled.modes[0] is not navigation.modes[0]
        assert scaled.modes[0].walkSpeed == pytest.approx(WALK_SPEED * 4.0)
        assert navigation.modes[0].walkSpeed == pytest.approx(WALK_SPEED)
        assert list(scaled.modeSwitching) == ['keys']
        assert isinstance(scaled.modes[1], ExamineMode)

    def test_it_declares_the_examine_mode_by_default(self):
        """A context that says nothing moves as an interactive one always has:
        the classic arrow-key and drag navigation, and one view."""
        navigation = nd.defaultNavigation()
        assert [mode.name for mode in navigation.modes] == ['examine']
        assert navigation.views is None or navigation.views == vrmlnode.NULL
        assert list(navigation.modeSwitching) == []

    def test_the_mode_in_force_is_not_a_setting(self):
        assert 'current' in nd.Navigation.TRANSIENT_FIELDS


class TestViews:
    def _editor(self):
        return nd.Views(
            views=[
                nd.ViewDefinition(name='top', camera='top', gestures=['plan']),
                nd.ViewDefinition(name='front', camera='front', gestures=['plan']),
                nd.ViewDefinition(name='left', camera='left', gestures=['plan']),
                nd.ViewDefinition(name='perspective', camera='perspective'),
            ],
            arrangements=[
                nd.Arrangement(name='single', views=['perspective']),
                nd.Arrangement(name='quad', views=['top', 'front', 'left', 'perspective']),
            ],
            arrangement='quad',
            switching=['keys', 'controls'],
        )

    def test_a_declaration_names_what_each_arrangement_shows(self):
        views = self._editor()
        assert views.arrangementViews() == {
            'single': ('perspective',),
            'quad': ('top', 'front', 'left', 'perspective'),
        }

    def test_a_camera_is_one_of_the_kinds_the_engine_builds(self):
        with pytest.raises(ValueError, match='perspective'):
            nd.ViewDefinition(name='odd', camera='fisheye')

    def test_an_arrangement_names_views_that_are_declared(self):
        with pytest.raises(ValueError, match='nowhere'):
            nd.Views(views=[nd.ViewDefinition(name='perspective')],
                     arrangements=[nd.Arrangement(name='single', views=['nowhere'])])

    def test_an_arrangement_places_one_two_or_four_views(self):
        with pytest.raises(ValueError, match='three'):
            nd.Views(views=[nd.ViewDefinition(name=name, camera=name)
                            for name in ('top', 'front', 'left')],
                     arrangements=[nd.Arrangement(name='three',
                                                  views=['top', 'front', 'left'])])

    def test_the_arrangement_shown_first_is_one_declared(self):
        with pytest.raises(ValueError, match='sideways'):
            nd.Views(views=[nd.ViewDefinition(name='perspective')],
                     arrangements=[nd.Arrangement(name='single', views=['perspective'])],
                     arrangement='sideways')

    def test_switching_names_a_known_way(self):
        with pytest.raises(ValueError, match='controls'):
            nd.Views(views=[nd.ViewDefinition(name='perspective')], switching=['voice'])

    def test_gestures_name_registered_ones(self):
        with pytest.raises(KeyError, match='no-such-gesture'):
            nd.ViewDefinition(name='top', camera='top', gestures=['no-such-gesture'])


class TestTheModeNamedAtStart:
    def names(self, navigation):
        return [mode.name for mode in navigation.modes]

    def test_a_mode_named_alone_is_the_only_one_declared(self):
        assert self.names(nd.Navigation(mode='fly')) == ['fly']

    def test_a_mode_the_list_lacks_is_declared_with_it(self):
        navigation = nd.Navigation(modes=['examine'], mode='fly')
        assert self.names(navigation) == ['examine', 'fly']

    def test_a_mode_already_declared_is_not_declared_twice(self):
        navigation = nd.Navigation(modes=['fly', 'walk'], mode='walk')
        assert self.names(navigation) == ['fly', 'walk']

    def test_a_mode_given_as_a_node_counts_by_its_name(self):
        navigation = nd.Navigation(modes=[FlyMode(name='fly')], mode='fly')
        assert self.names(navigation) == ['fly']

    def test_no_mode_named_declares_nothing_more(self):
        assert self.names(nd.Navigation(modes=['walk'])) == ['walk']
        assert self.names(nd.Navigation()) == []

    def test_a_name_that_is_registered_nowhere_is_refused(self):
        with pytest.raises(KeyError, match='no-such-mode'):
            nd.Navigation(mode='no-such-mode')

    def test_the_navigation_manager_starts_in_it(self):
        from OpenGLContext.move.navigation import NavigationManager
        definition = ContextDefinition(navigation={'mode': 'fly'})
        manager = NavigationManager(definition, platform=None)
        assert manager.current.name == 'fly'


class TestTheDefinitionField:
    def test_a_fresh_definition_navigates_as_it_always_has(self):
        navigation = ContextDefinition().navigation
        assert [mode.name for mode in navigation.modes] == ['examine']

    def test_each_definition_has_a_navigation_of_its_own(self):
        assert ContextDefinition().navigation is not ContextDefinition().navigation

    def test_null_means_no_navigation(self):
        definition = ContextDefinition(navigation=None)
        assert not definition.navigation

    def test_a_definition_naming_other_fields_keeps_the_default_navigation(self):
        definition = ContextDefinition(profile='compatibility')
        assert [mode.name for mode in definition.navigation.modes] == ['examine']

    def test_a_mapping_is_the_fields_of_a_navigation(self):
        definition = ContextDefinition(navigation={'modes': ['fly']})
        assert [mode.name for mode in definition.navigation.modes] == ['fly']

    def test_physics_and_audio_take_a_bool_for_enabled(self):
        definition = ContextDefinition(physics=False, audio=False)
        assert not definition.physics.enabled
        assert not definition.audio.enabled

    def test_physics_and_audio_take_a_mapping_of_their_fields(self):
        definition = ContextDefinition(physics={'tickHz': 240.0},
                                       audio={'enabled': False})
        assert definition.physics.tickHz == 240.0
        assert not definition.audio.enabled

    @pytest.mark.parametrize('value', [True, False])
    def test_navigation_refuses_a_bool_and_says_what_it_takes(self, value):
        """A Navigation has no ``enabled``; ``None`` is the one with no modes."""
        with pytest.raises(ValueError, match='navigation=None'):
            ContextDefinition(navigation=value)

    @pytest.mark.parametrize('key', ['physics', 'audio'])
    def test_an_integer_is_not_taken_for_a_bool(self, key):
        with pytest.raises(ValueError):
            ContextDefinition(**{key: 1})

    def test_a_mapping_naming_no_field_is_refused_by_name(self):
        with pytest.raises(AttributeError, match='bogus'):
            ContextDefinition(audio={'bogus': 1})

    def test_it_is_not_offered_as_a_rendering_setting(self):
        assert 'navigation' not in ContextDefinition.UI_HINTS


class TestTheOldFieldsForward:
    """``movementModes`` and ``movementMode`` read and write ``navigation``
    for one release, with a warning."""

    def test_setting_the_modes_keeps_the_classic_navigation(self):
        definition = ContextDefinition()
        with pytest.warns(DeprecationWarning):
            definition.movementModes = [WalkMode(name='walk')]
        names = [mode.name for mode in definition.navigation.modes]
        assert names == ['examine', 'walk']

    def test_reading_the_modes_answers_the_ones_that_move_a_body(self):
        definition = ContextDefinition(navigation=nd.Navigation(modes=['examine', 'fly']))
        with pytest.warns(DeprecationWarning):
            modes = definition.movementModes
        assert [mode.name for mode in modes] == ['fly']

    def test_a_definition_with_only_the_classic_navigation_declares_no_modes(self):
        """What a host asks before declaring modes of its own."""
        with pytest.warns(DeprecationWarning):
            assert not ContextDefinition().movementModes

    def test_the_constructor_takes_them_too(self):
        with pytest.warns(DeprecationWarning):
            definition = ContextDefinition(movementModes=[FlyMode(name='fly')])
        assert [mode.name for mode in definition.navigation.modes] == ['examine', 'fly']

    def test_the_mode_in_force_reads_and_writes_current(self):
        definition = ContextDefinition()
        flying = FlyMode(name='fly')
        with pytest.warns(DeprecationWarning):
            definition.movementMode = flying
        assert definition.navigation.current is flying
        with pytest.warns(DeprecationWarning):
            assert definition.movementMode is flying


def test_every_registered_mode_is_a_movement_mode():
    for name in nd.registeredModes():
        assert isinstance(nd.movementMode(name), MovementMode)
