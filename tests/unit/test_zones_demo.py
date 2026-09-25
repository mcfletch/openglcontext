"""``oglc-zones``: the court's zones, with no window.

The scene the demo and its tutorial draw is :class:`ZoneCourt`, so what each
zone holds and what the keys do are tested here; ``tests/zones_demo.py`` is
the rendered form, in the visual suite.
"""
import pytest

from OpenGLContext.bin import zones_demo
from OpenGLContext.bin.zones_demo import ROOM, ROOM_X, ZoneCourt
from OpenGLContext.scenegraph import zone as zonenodes


@pytest.fixture(scope='module')
def finishes():
    return zones_demo.Finishes()


@pytest.fixture
def court(finishes):
    return ZoneCourt(finishes)


def settings_of(zone, kind):
    return [setting for setting in zone.settings if isinstance(setting, kind)]


class TestTheRooms:
    def test_each_room_is_a_zone_the_size_of_its_inside(self, court):
        for name in ROOM_X:
            assert tuple(court.zones[name].size) == pytest.approx(ROOM)
            assert tuple(court.holders[name].translation)[0] == \
                pytest.approx(ROOM_X[name])

    def test_each_room_names_its_own_lamp_and_no_other(self, court):
        for name in ROOM_X:
            lights, = settings_of(court.zones[name], zonenodes.ZoneLights)
            assert list(lights.lights) == [court.lamps[name]]
        assert court.lamps['west'] is not court.lamps['east']

    def test_the_lamps_are_in_the_scene(self, court):
        for lamp in court.lamps.values():
            assert lamp in court.children

    def test_the_west_room_is_shaded_and_the_east_room_captured(self, court):
        west, = settings_of(court.zones['west'], zonenodes.ZoneEnvironment)
        east, = settings_of(court.zones['east'], zonenodes.ZoneEnvironment)
        assert west.intensity == pytest.approx(zones_demo.ROOF_SHADE)
        assert not west.capture
        assert east.capture

    def test_the_statue_is_shown_in_its_room_and_hidden_elsewhere(self, court):
        shown, = settings_of(court.zones['east'], zonenodes.ZoneVisibility)
        hidden, = settings_of(court.zones['court'], zonenodes.ZoneVisibility)
        assert list(shown.nodes) == [court.statue] and shown.visible
        assert list(hidden.nodes) == [court.statue] and not hidden.visible
        assert court.zones['east'].priority > court.zones['court'].priority


class TestTheKeys:
    def test_z_takes_the_rooms_zones_away_and_back(self, court):
        assert court.press('z') == 'zones off'
        assert not court.placed('west') and not court.placed('east')
        assert court.placed('court')
        assert court.press('z') == 'zones on'
        assert court.placed('west') and court.placed('east')

    def test_t_shows_the_statue_everywhere_and_back(self, court):
        assert 'everywhere' in court.press('t')
        assert not court.placed('court')
        assert 'only inside' in court.press('t')
        assert court.placed('court')

    def test_any_other_key_changes_nothing(self, court):
        assert court.press('q') == ''
        assert all(court.placed(name) for name in court.holders)


class TestTheCommand:
    def test_help_prints_the_keys_and_opens_no_window(self, capsys):
        with pytest.raises(SystemExit) as stopped:
            zones_demo.main(['--help'])
        assert stopped.value.code == 0
        said = capsys.readouterr().out
        assert 'usage: oglc-zones' in said
        for key in ZoneCourt.KEYS:
            assert '  %s -- ' % (key,) in said
