"""An OBJ document as a scene: parts as transforms, meshes as shapes, materials applied.

Read through the loader the way an application reads one, from files in
``tmp_path``. No GL: the nodes are built and read back.
"""
from __future__ import annotations

import gzip
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from OpenGL.GL import GL_LINES, GL_POINTS, GL_TRIANGLES
from PIL import Image

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.obj import OBJHandler
from OpenGLContext.scenegraph import basenodes
from OpenGLContext.scenegraph.imagetexture import ImageTexture
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.viewer.adapters.scenegraph import SceneGraphAdapter

SQUARE = 'v 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\n'


def write(tmp_path: Path, text: str, name: str = 'model.obj', **files: str) -> str:
    path = tmp_path / name
    path.write_text(text)
    for filename, content in files.items():
        (tmp_path / filename.replace('_dot_', '.')).write_text(content)
    return str(path)


def shapes_of(scene: Any) -> list[Any]:
    return [shape for transform in scene.children for shape in transform.children]


class TestStructure:
    def test_one_transform_per_part_one_shape_per_mesh(self, tmp_path: Path) -> None:
        path = write(tmp_path, SQUARE + 'o A\nusemtl x\nf 1 2 3\nusemtl y\nf 1 3 4\no B\nf 1 2 4\n')
        scene = Loader.load(path)
        assert [len(transform.children) for transform in scene.children] == [2, 1]
        assert all(isinstance(transform, basenodes.Transform) for transform in scene.children)

    def test_a_shape_holds_a_pbr_mesh_drawn_from_both_sides(self, tmp_path: Path) -> None:
        scene = Loader.load(write(tmp_path, SQUARE + 'f 1 2 3 4\n'))
        shape, = shapes_of(scene)
        assert isinstance(shape.geometry, PBRMesh)
        assert shape.geometry.draw_mode == GL_TRIANGLES
        assert shape.geometry.solid is False
        assert len(shape.geometry.indices) == 6

    def test_named_parts_are_found_by_def(self, tmp_path: Path) -> None:
        scene = Loader.load(write(tmp_path, SQUARE + 'o Chimney\nf 1 2 3\n'))
        assert scene.getDEF('Chimney') is scene.children[0]

    def test_an_unnamed_part_has_no_def(self, tmp_path: Path) -> None:
        scene = Loader.load(write(tmp_path, SQUARE + 'f 1 2 3\n'))
        assert not scene.children[0].DEF

    def test_lines_and_points_draw_as_lines_and_points(self, tmp_path: Path) -> None:
        scene = Loader.load(write(tmp_path, SQUARE + 'f 1 2 3\nl 1 3\np 4\n'))
        assert sorted(shape.geometry.draw_mode for shape in shapes_of(scene)) == [
            GL_POINTS, GL_LINES, GL_TRIANGLES]

    def test_vertex_colours_reach_the_mesh_and_leave_the_default_material_white(self, tmp_path: Path) -> None:
        text = 'v 0 0 0 1 0 0\nv 1 0 0 0 1 0\nv 0 1 0 0 0 1\nf 1 2 3\n'
        shape, = shapes_of(Loader.load(write(tmp_path, text)))
        assert shape.geometry.colors is not None
        assert list(shape.appearance.material.baseColor) == pytest.approx([1, 1, 1])

    def test_a_file_with_no_geometry_is_an_empty_scene(self, tmp_path: Path) -> None:
        scene = Loader.load(write(tmp_path, '# nothing\n'))
        assert list(scene.children) == []

    def test_a_gzipped_file(self, tmp_path: Path) -> None:
        path = tmp_path / 'model.obj.gz'
        path.write_bytes(gzip.compress((SQUARE + 'f 1 2 3 4\n').encode()))
        assert len(shapes_of(Loader.load(str(path)))) == 1

    def test_loads_reads_bytes_held_in_memory(self, tmp_path: Path) -> None:
        scene = Loader.loads((SQUARE + 'f 1 2 3 4\n').encode(), str(tmp_path / 'memory.obj'))
        assert len(shapes_of(scene)) == 1

    def test_a_gzipped_document_in_memory(self, tmp_path: Path) -> None:
        data = gzip.compress((SQUARE + 'f 1 2 3 4\n').encode())
        assert len(shapes_of(OBJHandler().parse(data, str(tmp_path / 'memory.obj'))[1])) == 1

    def test_a_malformed_file_raises_naming_it_and_the_line(self, tmp_path: Path) -> None:
        path = write(tmp_path, 'v 0 0 0\nv 1 x 0\n', name='bad.obj')
        with pytest.raises(ValueError, match=r'bad\.obj:2'):
            Loader.load(path)

    def test_free_form_geometry_is_reported_once(self, tmp_path: Path, caplog: Any) -> None:
        path = write(tmp_path, SQUARE + 'cstype bspline\ncurv 0 1 1 2 3\ncurv 0 1 4 3 2\nf 1 2 3\n')
        with caplog.at_level(logging.WARNING):
            Loader.load(path)
        messages = [record.getMessage() for record in caplog.records if 'free-form' in record.getMessage()]
        assert len(messages) == 1 and '3 free-form' in messages[0]

    def test_the_viewer_can_frame_the_scene(self, tmp_path: Path) -> None:
        scene = Loader.load(write(tmp_path, SQUARE + 'f 1 2 3 4\n'))
        framed = SceneGraphAdapter().sceneFrom(scene)
        assert framed.radius > 0
        assert np.allclose(framed.center, (0.5, 0.5, 0), atol=1e-4)


class TestMaterials:
    def test_usemtl_applies_the_library_material(self, tmp_path: Path) -> None:
        path = write(tmp_path, 'mtllib model.mtl\n' + SQUARE + 'usemtl red\nf 1 2 3 4\n',
                     model_dot_mtl='newmtl red\nKd 1 0 0\nPr 0.25\n')
        shape, = shapes_of(Loader.load(path))
        material = shape.appearance.material
        assert isinstance(material, PhysicalMaterial)
        assert list(material.baseColor) == pytest.approx([1, 0, 0])
        assert material.roughness == pytest.approx(0.25)

    def test_one_material_is_one_appearance(self, tmp_path: Path) -> None:
        path = write(tmp_path, 'mtllib model.mtl\n' + SQUARE
                     + 'usemtl red\no A\nf 1 2 3\no B\nf 1 3 4\n', model_dot_mtl='newmtl red\nKd 1 0 0\n')
        first, second = shapes_of(Loader.load(path))
        assert first.appearance is second.appearance
        assert first.geometry.appearance is first.appearance

    def test_two_materials_are_two_appearances(self, tmp_path: Path) -> None:
        path = write(tmp_path, 'mtllib model.mtl\n' + SQUARE + 'usemtl a\nf 1 2 3\nusemtl b\nf 1 3 4\n',
                     model_dot_mtl='newmtl a\nKd 1 0 0\nnewmtl b\nKd 0 0 1\n')
        first, second = shapes_of(Loader.load(path))
        assert list(first.appearance.material.baseColor) == pytest.approx([1, 0, 0])
        assert list(second.appearance.material.baseColor) == pytest.approx([0, 0, 1])

    def test_faces_with_no_material_are_light_grey(self, tmp_path: Path) -> None:
        shape, = shapes_of(Loader.load(write(tmp_path, SQUARE + 'f 1 2 3 4\n')))
        assert list(shape.appearance.material.baseColor) == pytest.approx([0.8] * 3)

    def test_a_material_no_library_defines_is_the_default_and_is_reported_once(
            self, tmp_path: Path, caplog: Any) -> None:
        path = write(tmp_path, SQUARE + 'usemtl ghost\no A\nf 1 2 3\no B\nf 1 3 4\n')
        with caplog.at_level(logging.WARNING):
            first, second = shapes_of(Loader.load(path))
        assert list(first.appearance.material.baseColor) == pytest.approx([0.8] * 3)
        assert first.appearance is second.appearance
        assert caplog.text.count("'ghost'") == 1

    def test_a_missing_library_still_loads_the_geometry(self, tmp_path: Path, caplog: Any) -> None:
        path = write(tmp_path, 'mtllib gone.mtl\n' + SQUARE + 'usemtl red\nf 1 2 3 4\n')
        with caplog.at_level(logging.WARNING):
            shapes = shapes_of(Loader.load(path))
        assert len(shapes) == 1
        assert 'gone.mtl' in caplog.text

    def test_a_textured_model_end_to_end(self, tmp_path: Path) -> None:
        Image.new('RGB', (4, 4), (200, 50, 20)).save(tmp_path / 'brick.png')
        text = ('mtllib model.mtl\n' + SQUARE + 'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n'
                'usemtl brick\nf 1/1 2/2 3/3 4/4\n')
        path = write(tmp_path, text, model_dot_mtl='newmtl brick\nmap_Kd brick.png\n')
        shape, = shapes_of(Loader.load(path))
        texture = shape.appearance.material.baseTexture
        assert isinstance(texture, ImageTexture)
        assert texture.url[0].endswith('brick.png')
        assert shape.geometry.texcoords is not None


class TestTangents:
    def test_a_normal_mapped_material_gives_its_mesh_tangents(self, tmp_path: Path) -> None:
        Image.new('RGB', (4, 4), (128, 128, 255)).save(tmp_path / 'n.png')
        text = ('mtllib model.mtl\n' + SQUARE + 'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\n'
                'usemtl m\nf 1/1 2/2 3/3 4/4\n')
        path = write(tmp_path, text, model_dot_mtl='newmtl m\nnorm n.png\n')
        shape, = shapes_of(Loader.load(path))
        tangents = shape.geometry.tangents
        assert tangents is not None and tangents.shape == (len(shape.geometry.positions), 4)
        # u runs along +x on this quad, and the handedness is 1 for a right-handed frame
        assert np.allclose(tangents[:, :3], (1, 0, 0), atol=1e-5)
        assert np.allclose(tangents[:, 3], 1.0)

    def test_a_material_without_one_has_none(self, tmp_path: Path) -> None:
        text = SQUARE + 'vt 0 0\nvt 1 0\nvt 1 1\nvt 0 1\nf 1/1 2/2 3/3 4/4\n'
        shape, = shapes_of(Loader.load(write(tmp_path, text)))
        assert shape.geometry.tangents is None

    def test_names_that_are_not_x3d_identifiers_are_kept_as_written(self, tmp_path: Path) -> None:
        scene = Loader.load(write(tmp_path, SQUARE + 'o Cube.001\nf 1 2 3\n'))
        assert scene.getDEF('Cube.001') is scene.children[0]
