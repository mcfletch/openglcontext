"""X3D's AcousticProperties: what a surface does to the sound heard.

A shape whose appearance has enabled AcousticProperties is a surface sound
meets. `absorption`, `diffuse` and `specular` are read as shares of the energy
striking it; what is left passes through it. A Sound or SpatialSound whose
straight path to the listener crosses the surface keeps that share of its
energy, once per crossing, so its gain is the share's square root. A listener
inside the box round the scene's surfaces hears a reverb whose decay is
Sabine's reverberation time for that room and whose level is the root of the
surfaces' mean reflection, laid under any zone's reverb.
"""
import math

import numpy as np
import pytest
from omi_audio.device import NullDevice
from omi_audio.engine import AudioEngine
from omi_audio.spatial import Listener
from vrml.x3d import nodes as x3d

from OpenGLContext.audio import acoustics, areas, x3dgraph
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph import x3dsound as snd

RATE = 8000


def surface(geometry, **properties):
    """A shape of `geometry` whose appearance has acoustic `properties`"""
    return basenodes.Shape(geometry=geometry, appearance=basenodes.Appearance(
        acousticProperties=x3d.AcousticProperties(**properties)))


def placed(x=0.0, y=0.0, z=0.0):
    matrix = np.identity(4)
    matrix[3, :3] = (x, y, z)
    return matrix


def wall(**properties):
    """A 10 m square wall in the plane z = 0, one face thick"""
    return surface(basenodes.IndexedFaceSet(
        coord=basenodes.Coordinate(point=[(-5, -5, 0), (5, -5, 0), (5, 5, 0), (-5, 5, 0)]),
        coordIndex=[0, 1, 2, 3, -1], solid=False), **properties)


class TestShares:
    def test_what_is_not_absorbed_or_reflected_passes(self):
        props = x3d.AcousticProperties(absorption=0.5, diffuse=0.2, specular=0.1)
        assert acoustics.transmission(props) == pytest.approx(0.2)
        assert acoustics.reflection(props) == pytest.approx(0.3)

    def test_the_shares_are_held_between_nought_and_one(self):
        props = x3d.AcousticProperties(absorption=0.9, diffuse=0.5, specular=0.5)
        assert acoustics.transmission(props) == 0.0
        assert acoustics.reflection(props) == 1.0

    def test_a_surface_of_defaults_passes_everything(self):
        assert acoustics.transmission(x3d.AcousticProperties()) == 1.0

    def test_only_an_enabled_node_on_the_appearance_counts(self):
        assert acoustics.properties_of(wall(absorption=1.0)) is not None
        assert acoustics.properties_of(wall(absorption=1.0, enabled=False)) is None
        assert acoustics.properties_of(basenodes.Shape(geometry=basenodes.Box())) is None


class TestOcclusion:
    def heard(self, *surfaces, source=(0, 0, -5), listener=(0, 0, 5)):
        found = acoustics.Acoustics()
        found.update(list(surfaces))
        return found.occlusion(source, listener)

    def test_a_wall_between_passes_its_share(self):
        assert self.heard((wall(absorption=0.5, diffuse=0.25), placed())) == pytest.approx(
            0.5, abs=1e-6)

    def test_a_wall_aside_passes_everything(self):
        assert self.heard((wall(absorption=1.0), placed(x=20))) == 1.0

    def test_a_wall_behind_the_listener_passes_everything(self):
        assert self.heard((wall(absorption=1.0), placed(z=8))) == 1.0

    def test_each_crossing_counts(self):
        # A box's near and far faces, each passing a half.
        room = surface(basenodes.Box(size=(4, 4, 4)), absorption=0.5)
        assert self.heard((room, placed())) == pytest.approx(0.5, abs=1e-6)

    def test_two_walls_multiply(self):
        first, second = wall(absorption=0.5), wall(specular=0.75)
        assert self.heard((first, placed(z=-1)), (second, placed(z=1))) == pytest.approx(
            math.sqrt(0.125), abs=1e-6)

    def test_no_surfaces_pass_everything(self):
        assert self.heard() == 1.0

    def test_a_moved_wall_is_met_where_it_now_is(self):
        found = acoustics.Acoustics()
        shape = wall(absorption=1.0)
        found.update([(shape, placed())])
        assert found.occlusion((0, 0, -5), (0, 0, 5)) == 0.0
        found.update([(shape, placed(x=20))])
        assert found.occlusion((0, 0, -5), (0, 0, 5)) == 1.0

    def test_a_changed_geometry_is_met_as_it_now_is(self):
        found = acoustics.Acoustics()
        shape = surface(basenodes.Box(size=(2, 2, 2)), absorption=1.0)
        found.update([(shape, placed())])
        assert found.occlusion((3, 0, -5), (3, 0, 5)) == 1.0
        shape.geometry.size = (8, 2, 2)
        found.update([(shape, placed())])
        assert found.occlusion((3, 0, -5), (3, 0, 5)) == 0.0

    def test_a_changed_property_is_read(self):
        found = acoustics.Acoustics()
        shape = wall(absorption=1.0)
        found.update([(shape, placed())])
        shape.appearance.acousticProperties.absorption = 0.5
        found.update([(shape, placed())])
        assert found.occlusion((0, 0, -5), (0, 0, 5)) == pytest.approx(math.sqrt(0.5))


class TestReverb:
    ROOM = (10.0, 4.0, 8.0)

    def room(self, **properties):
        found = acoustics.Acoustics()
        found.update([(surface(basenodes.Box(size=self.ROOM), **properties), placed())])
        return found

    def test_the_decay_is_sabines(self):
        found = self.room(absorption=0.2, diffuse=0.5, specular=0.3)
        x, y, z = self.ROOM
        volume, area = x * y * z, 2 * (x * y + y * z + x * z)
        reverb = found.reverb((0, 0, 0))
        assert reverb.decay == pytest.approx(0.161 * volume / (area * 0.2))
        assert reverb.level == pytest.approx(math.sqrt(0.8))

    def test_outside_the_room_there_is_none(self):
        assert self.room(diffuse=0.5).reverb((20, 0, 0)) is None

    def test_a_room_that_absorbs_nothing_rings_for_the_longest_decay(self):
        reverb = self.room(specular=1.0).reverb((0, 0, 0))
        assert reverb.decay == acoustics.MAX_DECAY

    def test_flat_surfaces_enclose_no_room(self):
        found = acoustics.Acoustics()
        found.update([(wall(diffuse=1.0), placed())])
        assert found.reverb((0, 0, 0)) is None

    def test_the_reverb_is_laid_under_the_applications_and_put_back(self):
        engine = AudioEngine(device=NullDevice(sample_rate=RATE), voices=4)
        try:
            engine.reverb.level, engine.reverb.decay = 0.125, 2.0
            ground = self.room(diffuse=0.5).reverb((0, 0, 0))
            areas.apply_zones(engine, [], [], (0, 0, 0), ground=ground)
            assert engine.reverb.level == pytest.approx(math.sqrt(0.5))
            assert engine.reverb.decay == pytest.approx(ground.decay)
            areas.apply_zones(engine, [], [], (0, 0, 0))
            assert (engine.reverb.level, engine.reverb.decay) == (0.125, 2.0)
        finally:
            engine.close()


class TestHeard:
    """A SpatialSound behind a wall, through the frame's SoundGraph"""

    @pytest.fixture
    def engine(self):
        made = AudioEngine(device=NullDevice(sample_rate=RATE), voices=8)
        yield made
        made.close()

    def level(self, engine, *surfaces):
        graph = x3dgraph.SoundGraph(engine)
        try:
            found = acoustics.Acoustics()
            found.update(list(surfaces))
            sound = snd.SpatialSound(children=[snd.OscillatorSource(frequency=440.0)])
            graph.update([(sound, placed(z=-5))], 1.0, acoustics=found,
                         listener=Listener())
            engine.mixer.mix(2048)
            block = engine.mixer.mix(2048)
            return float(np.sqrt(np.mean(np.square(block))))
        finally:
            graph.close()

    def test_a_wall_quietens_it_by_its_share(self, engine):
        clear = self.level(engine)
        behind = self.level(engine, (wall(absorption=0.75), placed(z=-2)))
        assert behind == pytest.approx(clear * 0.5, rel=0.05)

    def test_a_wall_that_passes_nothing_silences_it(self, engine):
        assert self.level(engine, (wall(absorption=1.0), placed(z=-2))) < 1e-6


def test_acoustic_properties_is_an_implemented_node():
    assert 'AcousticProperties' in prototypes()


def test_sabines_constant_is_in_seconds_per_metre():
    assert acoustics.SABINE == pytest.approx(24 * math.log(10) / 343, rel=0.01)
