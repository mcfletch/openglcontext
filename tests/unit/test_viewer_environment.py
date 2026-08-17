"""The backdrop, and whether the model brings its own light
(:mod:`OpenGLContext.viewer.environment`).

The sky a viewer shows and the environment its metals reflect have to be the
same one, or a chrome sphere reflects a room the viewer is not in.  These check
which backdrop each spec asks for, including the unset case that means "whatever
the image-based lighting probe loaded".
"""
import pytest

from OpenGLContext.scenegraph.background import Background
from OpenGLContext.scenegraph.light import DirectionalLight, PointLight
from OpenGLContext.viewer.environment import (
    background_for, count_lights, cube_background, hdr_background,
    horizon_background, sky_background,
)


def _faces(directory, missing=None):
    """Write a real one-pixel image per cube face; return the prefix."""
    from PIL import Image
    from OpenGLContext.passes.ibl import _CUBE_FACES
    for suffix, _ in _CUBE_FACES:
        if suffix == missing:
            continue
        Image.new('RGB', (1, 1)).save(directory / ('faces_%s.jpg' % suffix))
    return directory / 'faces_'


class _Node:
    def __init__(self, *children):
        self.children = list(children)


@pytest.fixture(autouse=True)
def _no_inherited_environment(monkeypatch):
    """An environment left set by another test would change every answer."""
    monkeypatch.delenv('OPENGLCONTEXT_ENV_HDR', raising=False)
    monkeypatch.delenv('OPENGLCONTEXT_ENV_CUBEMAP', raising=False)


class TestCountingLights:
    def test_a_dark_model_counts_none(self):
        assert count_lights(_Node(_Node(), _Node())) == 0

    def test_lights_are_found_at_any_depth(self):
        tree = _Node(_Node(DirectionalLight()), PointLight())
        assert count_lights(tree) == 2

    def test_a_light_at_the_root_counts(self):
        assert count_lights(DirectionalLight()) == 1

    def test_a_shared_subtree_is_counted_once(self):
        """A scenegraph may reach the same node by two paths."""
        shared = _Node(DirectionalLight())
        assert count_lights(_Node(shared, shared)) == 1

    def test_a_cycle_does_not_hang(self):
        root = _Node(DirectionalLight())
        root.children.append(root)
        assert count_lights(root) == 1

    def test_a_node_with_no_children_field_is_fine(self):
        assert count_lights(object()) == 0


class TestTheGradientSky:
    def test_it_is_a_background_with_sky_and_ground(self):
        sky = sky_background()
        assert isinstance(sky, Background)
        assert len(sky.skyColor) > 1
        assert len(sky.groundColor) > 0

    def test_the_zenith_is_bluer_than_the_horizon(self):
        """A sky that reads as sky: strong blue above, pale haze at eye level."""
        colours = sky_background().skyColor
        zenith, horizon = colours[0], colours[-1]
        assert zenith[2] - zenith[0] > horizon[2] - horizon[0]


class TestTheHorizonSky:
    """A world of finite extent runs out, and what a camera at ground level
    sees past the last of it is the background's lower half."""

    def test_it_keeps_the_sky_it_was_given(self):
        assert (list(map(tuple, horizon_background().skyColor))
                == list(map(tuple, sky_background().skyColor)))

    def test_its_ground_is_the_haze_and_not_the_earth(self):
        """Ground-coloured, the edge of the world is a wall of earth."""
        earth = sky_background().groundColor[0]
        haze = horizon_background().groundColor[0]
        assert haze[2] > haze[0]                    # bluer than it is red
        assert haze[2] > earth[2]

    def test_the_haze_carries_on_from_the_horizon(self):
        """The join has to be invisible: the band below the horizon is the same
        colour as the band above it."""
        sky = horizon_background()
        assert tuple(sky.groundColor[0]) == pytest.approx(tuple(sky.skyColor[-1]))

    def test_the_colour_can_be_chosen(self):
        sky = horizon_background(haze=(0.2, 0.3, 0.4))
        assert tuple(sky.groundColor[0]) == pytest.approx((0.2, 0.3, 0.4))
        assert tuple(sky.skyColor[-1]) == pytest.approx((0.2, 0.3, 0.4))

    def test_it_is_a_background_like_any_other(self):
        assert isinstance(horizon_background(), Background)


class TestWhichBackdrop:
    def test_none_draws_nothing(self):
        assert background_for('none') is None

    def test_sky_draws_the_gradient(self):
        assert isinstance(background_for('sky'), Background)

    def test_a_colour_triple_draws_a_flat_colour(self):
        background = background_for('0.1,0.2,0.3')
        assert tuple(background.skyColor[0]) == pytest.approx((0.1, 0.2, 0.3))

    def test_unset_falls_back_to_the_sky_with_no_environment_loaded(self):
        assert isinstance(background_for(None), Background)

    def test_cube_and_hdr_fall_back_to_the_sky_too(self):
        """Asked for the loaded environment when none is loaded, show a sky."""
        assert isinstance(background_for('cube'), Background)
        assert isinstance(background_for('hdr'), Background)

    @pytest.mark.parametrize('spec', ['1,2', 'blue', '1,2,3,4', ''])
    def test_an_unreadable_spec_says_so_and_shows_a_sky(self, spec):
        """A viewer that opens no window is worse than one with the wrong backdrop."""
        said = []
        assert isinstance(background_for(spec, said.append), Background)
        assert said and 'bad background' in said[0]

    def test_it_need_not_be_told_where_to_complain(self):
        assert isinstance(background_for('nonsense'), Background)


class TestTheLoadedEnvironmentAsSkybox:
    def test_no_panorama_means_no_hdr_skybox(self):
        assert hdr_background() is None

    def test_a_blank_panorama_variable_means_no_skybox(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '   ')
        assert hdr_background() is None

    def test_a_panorama_becomes_the_skybox(self, monkeypatch):
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/tmp/sky.hdr')
        background = hdr_background()
        assert background is not None
        assert list(background.url) == ['/tmp/sky.hdr']

    def test_the_panorama_wins_over_a_cubemap(self, monkeypatch, tmp_path):
        """Both loaded means the probe used the panorama, so it is what shows."""
        monkeypatch.setenv('OPENGLCONTEXT_ENV_HDR', '/tmp/sky.hdr')
        monkeypatch.setenv('OPENGLCONTEXT_ENV_CUBEMAP', str(_faces(tmp_path)))
        assert type(background_for(None)).__name__ == 'HDRBackground'

    def test_no_cubemap_prefix_means_no_cube_skybox(self):
        assert cube_background() is None

    def test_a_partial_face_set_is_refused(self, monkeypatch, tmp_path):
        """A skybox with holes in it is worse than the gradient."""
        prefix = _faces(tmp_path, missing='DN')
        monkeypatch.setenv('OPENGLCONTEXT_ENV_CUBEMAP', str(prefix))
        assert cube_background() is None

    def test_a_complete_face_set_becomes_the_skybox(self, monkeypatch, tmp_path):
        prefix = str(_faces(tmp_path))
        monkeypatch.setenv('OPENGLCONTEXT_ENV_CUBEMAP', prefix)
        background = cube_background()
        assert background is not None
        assert list(background.topUrl) == [prefix + 'UP.jpg']
        assert list(background.rightUrl) == [prefix + 'RT.jpg']
