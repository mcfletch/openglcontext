"""The sample world of each node: that there is one, that it loads, that its
VRML97 form is its X3D form, and that each circuit of sensors and interpolators
does what the sample says it does."""

import math

import numpy as np
import pytest
from PIL import Image

from vrml.x3d import files, pointing

from docbuild import nodesamples, nodeusage
from OpenGLContext.bin.x3d_regression import capture_time

SAMPLES = nodesamples.find()


def load(node):
    return files.load(nodesamples.Sample(node, '%s/%s.x3d' % (nodesamples.SAMPLES, node)).path)


def samples():
    return pytest.mark.parametrize('sample', SAMPLES, ids=lambda sample: sample.node)


class TestEveryNodeHasASample:
    def test_every_node_of_vrml97(self):
        assert nodesamples.unsampled(SAMPLES) == []

    def test_every_sample_is_for_a_node_there_is(self):
        from vrml.x3d import nodes

        assert [s.node for s in SAMPLES if not hasattr(nodes, s.node)] == []


class TestEachSample:
    @samples()
    def test_it_loads_without_a_fault(self, sample):
        assert nodesamples.problems(sample) == []

    @samples()
    def test_it_is_titled_for_its_node_and_says_what_it_shows(self, sample):
        meta = sample.meta()
        assert meta.get('title') == sample.node
        assert len(meta.get('description', '')) > 40

    @samples()
    def test_it_holds_the_node_it_is_for(self, sample):
        with open(sample.path, 'rb') as handle:
            found = nodeusage.scan_document(handle.read(), {sample.node}, sample.path)
        assert found, '%s does not use a %s' % (sample.path, sample.node)

    @samples()
    def test_the_frames_it_names_are_a_number(self, sample):
        assert sample.frames is None or sample.frames > 0

    @samples()
    def test_a_node_of_vrml97_has_its_vrml97_form_and_no_other_does(self, sample):
        import os

        assert os.path.exists(sample.wrl) == (sample.node in nodesamples.vrml97_nodes())

    def test_every_vrml97_form_is_what_its_x3d_form_converts_to(self):
        assert [s.wrl for s in nodesamples.stale(SAMPLES)] == []

    @samples()
    def test_the_vrml97_form_is_the_same_world(self, sample):
        import os

        if not os.path.exists(sample.wrl):
            pytest.skip('not a node of VRML97')
        program = sample.node == 'Script'
        assert scene_text(sample.wrl, program) == scene_text(sample.path, program)


def scene_text(path, program=False):
    """The world a document holds, as X3D XML without its head: the VRML97 form has
    no profile, version or meta to compare.  A Script's program is written inline
    by XML and as a url by VRML97, so ``program`` compares in VRML97 instead."""
    scene = files.load(path)
    if program:
        text = files.dumps(scene, 'classic', '2.0')
        return '\n'.join(line for line in text.splitlines() if not line.startswith('#'))
    text = files.dumps(scene, 'xml', canonical=True)
    return text[text.index('<Scene>') : text.index('</Scene>')]


def clock_at(scene, frames):
    """Run the sample's clock, the TimeSensor it DEFs as Clock, to the moment a
    render of ``frames`` frames is read."""
    now = capture_time(frames)
    scene.getDEF('Clock').advance(now)
    return now


def at_frames(node):
    scene = load(node)
    sample = nodesamples.Sample(node, '%s/%s.x3d' % (nodesamples.SAMPLES, node))
    return scene, clock_at(scene, sample.frames)


class TestTheCircuitsRunning:
    def test_a_time_sensor_turns_the_bar_a_quarter_turn_in_a_second(self):
        scene, _ = at_frames('TimeSensor')
        assert np.allclose(scene.getDEF('Rotor').rotation, [0, 0, 1, math.pi / 2], atol=1e-3)

    def test_an_orientation_interpolator_turns_part_of_the_way(self):
        scene, _ = at_frames('OrientationInterpolator')
        rotation = np.asarray(scene.getDEF('Rotor').rotation)
        assert np.allclose(rotation[:3], [math.sqrt(0.5), math.sqrt(0.5), 0], atol=1e-3)
        assert rotation[3] == pytest.approx(math.pi / 3, abs=1e-3)

    def test_a_position_interpolator_puts_the_ball_half_way_up_the_first_leg(self):
        scene, _ = at_frames('PositionInterpolator')
        assert np.allclose(scene.getDEF('Ball').translation, [-1.5, 1, 0], atol=1e-3)

    def test_a_scalar_interpolator_fades_the_box(self):
        scene, _ = at_frames('ScalarInterpolator')
        assert scene.getDEF('Skin').transparency == pytest.approx(0.4, abs=1e-3)

    def test_a_color_interpolator_passes_through_yellow(self):
        scene, _ = at_frames('ColorInterpolator')
        red, green, blue = scene.getDEF('Skin').diffuseColor
        assert red > 0.8 and green > 0.5 and blue < 0.3

    def test_a_coordinate_interpolator_lowers_the_apex(self):
        scene, _ = at_frames('CoordinateInterpolator')
        assert scene.getDEF('Apex').point[4][1] == pytest.approx(1.0, abs=1e-3)

    def test_a_normal_interpolator_turns_the_normals_toward_the_light(self):
        scene, _ = at_frames('NormalInterpolator')
        for vector in scene.getDEF('Facing').vector:
            assert np.allclose(vector, [math.sqrt(0.5), 0, math.sqrt(0.5)], atol=1e-3)


class TestTheCircuitsOperated:
    def test_a_click_on_the_touch_sensor_starts_a_turn(self):
        scene = load('TouchSensor')
        button = scene.getDEF('Button')
        hit = pointing.Hit((0, 0, 0.8), (0, 0, 1), (0.5, 0.5))
        button.pointerOver(hit)
        button.pointerPress(hit, pointing.Ray((0, 0, 5), (0, 0, -1)))
        button.pointerRelease(True, now=100.0)
        assert scene.getDEF('Clock').startTime == 100.0
        scene.getDEF('Clock').advance(100.5)
        assert scene.getDEF('Block').rotation[3] == pytest.approx(math.pi, abs=1e-3)

    def test_a_drag_on_the_plane_sensor_moves_the_ball_along_the_track(self):
        scene = load('PlaneSensor')
        sensor = scene.getDEF('Drag')
        sensor.pointerPress(pointing.Hit((0, 0, 0.4)), pointing.Ray((0, 0, 5), (0, 0, -1)))
        sensor.pointerDrag(None, pointing.Ray((2, 0, 5), (0, 0, -1)))
        assert np.allclose(scene.getDEF('Slider').translation, [2, 0, 0], atol=1e-3)

    def test_a_drag_past_the_end_of_the_track_stops_at_it(self):
        scene = load('PlaneSensor')
        sensor = scene.getDEF('Drag')
        sensor.pointerPress(pointing.Hit((0, 0, 0.4)), pointing.Ray((0, 0, 5), (0, 0, -1)))
        sensor.pointerDrag(None, pointing.Ray((9, 0, 5), (0, 0, -1)))
        assert scene.getDEF('Slider').translation[0] == pytest.approx(3.0)

    def test_a_drag_on_the_sphere_sensor_turns_the_sphere(self):
        scene = load('SphereSensor')
        sensor = scene.getDEF('Turn')
        sensor.pointerPress(pointing.Hit((0, 0, 1.5)), pointing.Ray((0, 0, 5), (0, 0, -1)))
        sensor.pointerDrag(None, pointing.Ray((0.9, 0, 5), (0, 0, -1)))
        rotation = np.asarray(scene.getDEF('Globe').rotation)
        assert rotation[3] > 0.1
        assert abs(rotation[1]) > 0.9

    def test_a_drag_round_the_cylinder_sensor_turns_the_knob_about_y(self):
        scene = load('CylinderSensor')
        sensor = scene.getDEF('Dial')
        sensor.pointerPress(pointing.Hit((1.2, 0, 0)), pointing.Ray((5, 0, 0), (-1, 0, 0)))
        sensor.pointerDrag(None, pointing.Ray((5, 0, 1.0), (-1, 0, 0)))
        rotation = np.asarray(scene.getDEF('Knob').rotation)
        assert abs(rotation[3]) > 0.1
        assert abs(rotation[1]) > 0.9

    def test_the_viewer_entering_the_proximity_zone_lights_the_lamp(self):
        scene = load('ProximitySensor')
        zone = scene.getDEF('Zone')
        zone.observe((0, 1, 0), (0, 1, 0, 0), now=50.0)
        assert zone.isActive
        glow = scene.getDEF('Glow')
        glow.advance(50.25)
        assert 0.4 < scene.getDEF('Lamp').emissiveColor[0] < 0.9
        glow.advance(50.6)
        assert np.allclose(scene.getDEF('Lamp').emissiveColor, [1, 0.9, 0.2], atol=1e-3)

    def test_the_viewer_outside_the_zone_leaves_the_lamp_dim(self):
        scene = load('ProximitySensor')
        zone = scene.getDEF('Zone')
        zone.observe((9, 1, 0), (0, 1, 0, 0), now=50.0)
        assert not zone.active()

    def test_seeing_the_visibility_region_starts_the_spin(self):
        scene = load('VisibilitySensor')
        scene.getDEF('Seen').observe(True, now=70.0)
        scene.getDEF('Clock').advance(70.5)
        assert scene.getDEF('Spinner').rotation[3] == pytest.approx(math.pi, abs=1e-3)


class TestOnTheNodesPage:
    """Each node's class page shows its sample: the render and both sources."""

    @pytest.fixture
    def sample(self):
        return next(s for s in SAMPLES if s.node == 'Box')

    def test_the_block_names_the_sample_and_shows_its_sources(self, sample):
        text = nodesamples.section(sample, image=False)[0]
        assert text.startswith('.. rubric:: Sample world')
        assert sample.meta()['description'] in text
        assert '.. literalinclude:: /samples/nodes/Box.x3d\n   :language: xml' in text
        assert '.. literalinclude:: /samples/nodes/Box.wrl' in text

    def test_the_render_is_shown_where_there_is_one(self, sample):
        assert '.. image:: /images/samples/Box.png' in nodesamples.section(sample, image=True)[0]
        assert '.. image::' not in nodesamples.section(sample, image=False)[0]

    def test_a_node_vrml97_lacks_has_only_its_x3d_source(self, tmp_path):
        (tmp_path / 'Arc2D.x3d').write_text(
            '<X3D profile="Immersive" version="3.3"><head>'
            '<meta name="title" content="Arc2D"/><meta name="description" content="An arc."/>'
            '</head><Scene/></X3D>',
            encoding='utf8',
        )
        text = nodesamples.section(nodesamples.find(str(tmp_path))[0], image=False)[0]
        assert 'Arc2D.x3d' in text
        assert 'Arc2D.wrl' not in text

    def test_an_interactive_sample_says_so(self):
        sample = next(s for s in SAMPLES if s.node == 'TouchSensor')
        assert 'operate' in nodesamples.section(sample, image=False)[0]
        assert 'operate' not in nodesamples.section(
            next(s for s in SAMPLES if s.node == 'Box'), image=False)[0]

    def test_the_renders_are_copied_where_the_pages_read_them(self, tmp_path):
        baselines = tmp_path / 'baselines'
        baselines.mkdir()
        Image.new('RGB', (4, 4), (200, 0, 0)).save(baselines / 'Samples.Box.png')
        (baselines / 'Samples.Box.json').write_text('{}', encoding='utf8')
        copied = nodesamples.publish_images(str(baselines), str(tmp_path / 'images'))
        assert copied == {'Box'}
        assert (tmp_path / 'images' / 'Box.png').read_bytes() == (baselines / 'Samples.Box.png').read_bytes()
        assert sorted(p.name for p in (tmp_path / 'images').iterdir()) == ['Box.png']

    def test_a_pointer_file_is_not_a_render(self, tmp_path):
        """A checkout without its LFS objects holds a text pointer where the PNG is."""
        baselines = tmp_path / 'baselines'
        baselines.mkdir()
        (baselines / 'Samples.Box.png').write_text('version https://git-lfs.github.com/spec/v1\n', encoding='utf8')
        assert nodesamples.publish_images(str(baselines), str(tmp_path / 'images')) == set()

    def test_the_callable_for_the_api_pages_answers_a_node_class_its_sample(self):
        from vrml.x3d import nodes

        sections = nodesamples.class_sections(SAMPLES, images={'Box'})
        assert 'Box.x3d' in sections(nodes.Box)[0]
        assert sections(nodes.Arc2D) == []
        assert sections(dict) == []
