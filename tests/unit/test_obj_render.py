"""OBJ models as they are drawn (GL, PBR core).

The unit tests read the nodes back; this draws them, which is the only check of
the texture orientation, the alpha merge, and that lines and points reach the
screen.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

pytest.importorskip('glfw')

from OpenGLContext.loaders import background
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import basenodes
from tests.unit.glrender import base_env, frames_of

SIZE = (160, 160)
PATIENCE = 20.0

QUAD = ('v -1 -1 0\nv 1 -1 0\nv 1 1 0\nv -1 1 0\n'
        'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n')


@pytest.fixture
def env(monkeypatch: Any) -> Any:
    base_env(monkeypatch, OPENGLCONTEXT_SHADOWS='0', OPENGLCONTEXT_INSTANCE_MIN='999')
    return monkeypatch


def drawn(render_scene: Any, tmp_path: Path, obj: str, **files: Any) -> np.ndarray:
    """The last frame of ``obj`` (with the named side files written beside it) in a headlit view"""
    (tmp_path / 'model.obj').write_text(obj)
    for name, content in files.items():
        target = tmp_path / name.replace('_dot_', '.')
        if isinstance(content, Image.Image):
            content.save(target)
        else:
            target.write_text(content)
    scene = Loader.load(str(tmp_path / 'model.obj'))
    assert background.wait_for_idle(PATIENCE)
    children = [basenodes.Viewpoint(position=(0.0, 0.0, 2.6)),
                basenodes.NavigationInfo(headlight=True), *scene.children]
    return frames_of(render_scene, children, frames=3, size=SIZE)[-1].astype(int)


def quadrants(frame: np.ndarray) -> dict[str, np.ndarray]:
    height, width = frame.shape[:2]
    middle_y, middle_x, step = height // 2, width // 2, width // 8
    return {'top left': frame[middle_y - step, middle_x - step],
            'top right': frame[middle_y - step, middle_x + step],
            'bottom left': frame[middle_y + step, middle_x - step],
            'bottom right': frame[middle_y + step, middle_x + step]}


def four_colours() -> Image.Image:
    """Red and green over blue and white, as a picture reads"""
    image = Image.new('RGB', (2, 2))
    image.putpixel((0, 0), (255, 0, 0))
    image.putpixel((1, 0), (0, 255, 0))
    image.putpixel((0, 1), (0, 0, 255))
    image.putpixel((1, 1), (255, 255, 255))
    return image


@pytest.mark.usefixtures('env')
def test_a_diffuse_map_puts_the_pictures_top_at_the_top_of_the_quad(render_scene, tmp_path):
    frame = drawn(render_scene, tmp_path, 'mtllib model.mtl\n' + QUAD + 'usemtl m\nf 1/1 2/2 3/3 4/4\n',
                  model_dot_mtl='newmtl m\nmap_Kd four.png\nPr 1\n', four_dot_png=four_colours())
    found = quadrants(frame)
    assert found['top left'].argmax() == 0 and found['top left'][0] > 100
    assert found['top right'].argmax() == 1 and found['top right'][1] > 100
    assert found['bottom left'].argmax() == 2 and found['bottom left'][2] > 100
    assert found['bottom right'].min() > 60


@pytest.mark.usefixtures('env')
def test_an_opacity_map_cuts_the_surface_where_the_picture_is_clear(render_scene, tmp_path):
    # Opaque in the picture's top row: the quad's top half draws, the bottom does not.
    mask = np.zeros((4, 4), np.uint8)
    mask[:2, :] = 255
    frame = drawn(render_scene, tmp_path,
                  'mtllib model.mtl\n' + QUAD + 'usemtl m\nf 1/1 2/2 3/3 4/4\n',
                  model_dot_mtl='newmtl m\nKd 1 1 1\nmap_d mask.png\n',
                  mask_dot_png=Image.fromarray(mask, 'L'))
    found = quadrants(frame)
    assert found['top left'].max() > 60 and found['top right'].max() > 60
    assert found['bottom left'].max() < 20 and found['bottom right'].max() < 20


@pytest.mark.usefixtures('env')
def test_vertex_colours_are_drawn(render_scene, tmp_path):
    text = ('v -1 -1 0 1 0 0\nv 1 -1 0 0 1 0\nv 1 1 0 0 0 1\nv -1 1 0 1 1 0\nf 1 2 3 4\n')
    frame = drawn(render_scene, tmp_path, text)
    width, height = SIZE
    near = {'red': frame[int(height * 0.8), int(width * 0.2)],
            'green': frame[int(height * 0.8), int(width * 0.8)],
            'blue': frame[int(height * 0.2), int(width * 0.8)],
            'yellow': frame[int(height * 0.2), int(width * 0.2)]}
    assert near['red'].argmax() == 0 and near['red'][0] > 1.5 * near['red'][1]
    assert near['green'].argmax() == 1 and near['green'][1] > 1.5 * near['green'][0]
    assert near['blue'].argmax() == 2 and near['blue'][2] > 1.5 * near['blue'][0]
    assert near['yellow'][2] < 0.75 * near['yellow'][:2].min()


@pytest.mark.usefixtures('env')
def test_a_material_colour_is_drawn(render_scene, tmp_path):
    frame = drawn(render_scene, tmp_path, 'mtllib model.mtl\n' + QUAD + 'usemtl m\nf 1 2 3 4\n',
                  model_dot_mtl='newmtl m\nKd 0 0.8 0\n')
    middle = frame[SIZE[1] // 2, SIZE[0] // 2]
    assert middle[1] > 60 and middle[0] < middle[1] and middle[2] < middle[1]


@pytest.mark.usefixtures('env')
def test_lines_reach_the_screen(render_scene, tmp_path):
    frame = drawn(render_scene, tmp_path, 'v -1 0 0\nv 1 0 0\nl 1 2\n')
    row = frame[SIZE[1] // 2 - 2:SIZE[1] // 2 + 3]
    assert row.max() > 40


@pytest.mark.usefixtures('env')
def test_points_reach_the_screen(render_scene, tmp_path):
    frame = drawn(render_scene, tmp_path, 'v 0 0 0\np 1\n')
    centre = frame[SIZE[1] // 2 - 3:SIZE[1] // 2 + 4, SIZE[0] // 2 - 3:SIZE[0] // 2 + 4]
    assert centre.max() > 40


def tilted(toward: tuple[float, float]) -> Image.Image:
    """A flat normal map whose every texel leans toward (x, y), x to the right and y up the picture"""
    nx, ny = toward
    nz = (1.0 - nx * nx - ny * ny) ** 0.5
    return Image.new('RGB', (4, 4), tuple(int(round((v * 0.5 + 0.5) * 255)) for v in (nx, ny, nz)))


def lit_quad(render_scene: Any, tmp_path: Path, normal_map: Image.Image, direction: tuple[float, float, float]) -> float:
    """The mean brightness of a normal-mapped quad lit from the side ``direction`` comes from"""
    (tmp_path / 'model.obj').write_text('mtllib model.mtl\n' + QUAD + 'usemtl m\nf 1/1 2/2 3/3 4/4\n')
    (tmp_path / 'model.mtl').write_text('newmtl m\nKd 1 1 1\nPr 0.9\nillum 1\nnorm tilt.png\n')
    normal_map.save(tmp_path / 'tilt.png')
    scene = Loader.load(str(tmp_path / 'model.obj'))
    assert background.wait_for_idle(PATIENCE)
    children = [basenodes.Viewpoint(position=(0.0, 0.0, 2.6)),
                basenodes.NavigationInfo(headlight=False),
                basenodes.DirectionalLight(direction=direction, intensity=1.0), *scene.children]
    frame = frames_of(render_scene, children, frames=3, size=SIZE)[-1].astype(float)
    width, height = SIZE
    return float(frame[height // 3:2 * height // 3, width // 3:2 * width // 3].mean())


@pytest.mark.usefixtures('env')
@pytest.mark.parametrize('axis, light', [
    ('u', (-1.0, 0.0, -1.0)),    # light travelling toward -x, so shining from the right
    ('v', (0.0, -1.0, -1.0)),    # light travelling down, so shining from above
])
def test_a_normal_map_leans_the_surface_toward_the_side_it_names(render_scene, tmp_path, axis, light):
    toward = (0.8, 0.0) if axis == 'u' else (0.0, 0.8)
    away = (-toward[0], -toward[1])
    for name in ('toward', 'away'):
        (tmp_path / name).mkdir()
    towards_light = lit_quad(render_scene, tmp_path / 'toward', tilted(toward), light)
    away_from_light = lit_quad(render_scene, tmp_path / 'away', tilted(away), light)
    assert towards_light > away_from_light + 5.0
