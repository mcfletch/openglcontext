"""A corpus of OBJ files in the dialects exporters write, checked against its manifest.

``tests/unit/obj_corpus/manifest.json`` states what a correct reader finds in
each file; ``tests/unit/objcorpus.py`` holds the arithmetic. Damaged copies of
every file (lines dropped, bytes truncated, numbers replaced) either read, to
arrays that are internally consistent, or raise ``ValueError``.
``test_obj_trimesh.py`` compares the same files with an independent reader.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.mtlfile import parse_mtl
from OpenGLContext.loaders.objfile import parse_obj
from tests.unit.objcorpus import (
    CORPUS, MANIFEST, NAMES, bounds_of, check_consistent, corner_positions, damaged, read,
    surface_area,
)

@pytest.mark.parametrize('name', NAMES)
class TestManifest:
    def test_the_file_reads_to_consistent_arrays(self, name: str) -> None:
        check_consistent(read(name))

    def test_triangle_count_and_area(self, name: str) -> None:
        expected = MANIFEST[name]
        triangles = corner_positions(read(name))
        assert len(triangles) == expected['triangles']
        assert surface_area(triangles) == pytest.approx(expected['area'], rel=1e-5, abs=1e-6)

    def test_bounds(self, name: str) -> None:
        expected = MANIFEST[name]['bounds']
        found = bounds_of(read(name))
        if expected is None:
            assert found is None
        else:
            assert np.allclose(found, expected, atol=1e-5)

    def test_parts_and_their_materials(self, name: str) -> None:
        expected = MANIFEST[name]
        model = read(name)
        assert [part.name for part in model.parts] == expected['parts']
        found: dict[str, list[str]] = {}
        for part in model.parts:
            found[part.name] = list(dict.fromkeys(mesh.material for mesh in part.meshes))
        assert found == expected['materials']

    def test_vertex_colours_where_the_file_has_them(self, name: str) -> None:
        has = bool(MANIFEST[name].get('colors'))
        model = read(name)
        assert all((mesh.colors is not None) == has for part in model.parts for mesh in part.meshes)

    def test_texture_coordinates_where_the_file_has_them(self, name: str) -> None:
        has = bool(MANIFEST[name].get('texcoords'))
        model = read(name)
        assert all((mesh.texcoords is not None) == has for part in model.parts for mesh in part.meshes)

    def test_the_loader_builds_a_scene_with_the_same_parts(self, name: str, caplog: Any) -> None:
        expected = MANIFEST[name]
        with caplog.at_level(logging.WARNING):
            scene = Loader.load(str(CORPUS / name))
        assert [transform.DEF or '' for transform in scene.children] == expected['parts']


@pytest.mark.parametrize('name', [name for name in NAMES if 'vertices' in MANIFEST[name]])
def test_the_vertex_count_where_the_file_fixes_it(name: str) -> None:
    found = sum(len(mesh.positions) for part in read(name).parts for mesh in part.meshes)
    assert found == MANIFEST[name]['vertices']


@pytest.mark.parametrize('name', [name for name in NAMES if 'kinds' in MANIFEST[name]])
def test_lines_and_points_are_counted_in_primitives(name: str) -> None:
    found: dict[str, int] = {}
    for part in read(name).parts:
        for mesh in part.meshes:
            if mesh.kind != 'triangles':
                step = 2 if mesh.kind == 'lines' else 1
                found[mesh.kind] = found.get(mesh.kind, 0) + len(mesh.indices) // step
    assert found == MANIFEST[name]['kinds']


class TestMaterialLibraries:
    def test_each_library_in_the_corpus_parses(self) -> None:
        for path in sorted(CORPUS.rglob('*.mtl')):
            library = parse_mtl(path.read_bytes(), path.name)
            assert len(library) >= 1, path

    def test_the_blender_materials_hold_what_blender_wrote(self) -> None:
        material = parse_mtl((CORPUS / 'blender_cube.mtl').read_bytes(), 'blender_cube.mtl')['Material']
        assert material.shininess == 250 and material.ior == 1.45 and material.illum == 2
        assert material.opacity == 1.0 and material.specular == (0.5, 0.5, 0.5)

    def test_the_pbr_library_holds_every_extension_it_names(self) -> None:
        material = parse_mtl((CORPUS / 'pbr_quad.mtl').read_bytes(), 'pbr_quad.mtl')['panel']
        assert (material.roughness, material.metallic) == (0.35, 1.0)
        assert (material.clearcoat, material.clearcoat_roughness) == (0.5, 0.1)
        assert sorted(material.maps) == ['bump', 'diffuse', 'emissive', 'metallic', 'roughness']
        assert material.maps['diffuse'].scale == (2.0, 2.0, 1.0)
        assert material.maps['bump'].bump_multiplier == 0.8

    def test_the_windows_library_is_read_from_its_subdirectory_through_backslashes(self, caplog: Any) -> None:
        with caplog.at_level(logging.WARNING):
            scene = Loader.load(str(CORPUS / 'windows_paths.obj'))
        shape = scene.children[0].children[0]
        assert list(shape.appearance.material.baseColor) == pytest.approx([1, 1, 1]) or \
            list(shape.appearance.material.baseColor) == pytest.approx([0.6, 0.4, 0.2])
        assert 'crate_wood.png' in caplog.text


@pytest.mark.parametrize('name', NAMES)
def test_damaged_files_read_or_raise_value_error(name: str) -> None:
    original = (CORPUS / name).read_bytes()
    for seed in range(120):
        broken = damaged(original, seed)
        try:
            model = parse_obj(broken, name)
        except ValueError:
            continue
        check_consistent(model)


@pytest.mark.parametrize('path', sorted(CORPUS.rglob('*.mtl')), ids=lambda path: path.name)
def test_damaged_libraries_read_or_raise_value_error(path: Path) -> None:
    original = path.read_bytes()
    for seed in range(120):
        try:
            library = parse_mtl(damaged(original, seed), path.name)
        except ValueError:
            continue
        for name, material in library.items():
            assert material.name == name
            for texture in material.maps.values():
                assert texture.file
            numbers = [material.shininess, material.opacity, material.ior, material.roughness,
                       material.metallic, *(material.diffuse or ()), *(material.specular or ())]
            assert all(value is None or np.isfinite(value) for value in numbers)
