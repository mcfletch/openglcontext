"""MTL materials as ``PhysicalMaterial`` appearances, and libraries found beside the model.

No GL: the nodes are built and read back. Image files are written by the tests.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from PIL import Image

from OpenGLContext.loaders.mtlfile import parse_mtl
from OpenGLContext.loaders.objmaterials import (
    LibraryMaterial, MaterialBuilder, load_libraries,
)
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.imagetexture import ImageTexture
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial


@pytest.fixture
def model(tmp_path: Path) -> str:
    """The path an OBJ in ``tmp_path`` would be read from"""
    return str(tmp_path / 'model.obj')


def png(path: Path, color: Any = (255, 0, 0), size: tuple[int, int] = (4, 4),
        mode: str = 'RGB') -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new(mode, size, color).save(path)
    return path


def build(model: str, text: str, directory: str = '') -> Any:
    """The Appearance of the one material in ``text``"""
    library = parse_mtl(text, 'test.mtl')
    entry = LibraryMaterial(next(iter(library.values())), directory)
    return MaterialBuilder(model).appearance(entry)


def physical(appearance: Any) -> PhysicalMaterial:
    assert isinstance(appearance.material, PhysicalMaterial)
    return appearance.material


class TestFactors:
    def test_diffuse_colour_is_the_base_colour(self, model: str) -> None:
        material = physical(build(model, 'newmtl m\nKd 0.2 0.4 0.6\n'))
        assert list(material.baseColor) == pytest.approx([0.2, 0.4, 0.6])

    def test_a_material_with_no_diffuse_colour_is_light_grey(self, model: str) -> None:
        assert list(physical(build(model, 'newmtl m\n')).baseColor) == pytest.approx([0.8] * 3)

    @pytest.mark.parametrize('shininess, roughness', [(0, 1.0), (250, 0.5), (1000, 0.0), (5000, 0.0)])
    def test_shininess_sets_roughness(self, model: str, shininess: float, roughness: float) -> None:
        material = physical(build(model, 'newmtl m\nNs %g\n' % shininess))
        assert material.roughness == pytest.approx(roughness, abs=0.01)

    def test_a_material_with_no_shininess_is_half_rough(self, model: str) -> None:
        assert physical(build(model, 'newmtl m\n')).roughness == pytest.approx(0.5, abs=0.01)

    def test_pr_outranks_shininess(self, model: str) -> None:
        material = physical(build(model, 'newmtl m\nNs 1000\nPr 0.3\n'))
        assert material.roughness == pytest.approx(0.3)

    def test_pm_is_metallic_and_the_default_is_dielectric(self, model: str) -> None:
        assert physical(build(model, 'newmtl m\nPm 0.8\n')).metallic == pytest.approx(0.8)
        assert physical(build(model, 'newmtl m\n')).metallic == 0.0

    def test_emission(self, model: str) -> None:
        material = physical(build(model, 'newmtl m\nKe 1 0.5 0\n'))
        assert list(material.emissiveColor) == pytest.approx([1, 0.5, 0])

    def test_specular_colour_sets_the_specular_strength(self, model: str) -> None:
        # Ks 0.5 is the usual default and is the engine's full dielectric highlight
        assert physical(build(model, 'newmtl m\nKs 0.5 0.5 0.5\n')).specular == pytest.approx(1.0)
        assert physical(build(model, 'newmtl m\nKs 0.25 0.25 0.25\n')).specular == pytest.approx(0.5)
        assert physical(build(model, 'newmtl m\nKs 0 0 0\n')).specular == pytest.approx(0.0)

    def test_illum_one_has_no_highlight(self, model: str) -> None:
        assert physical(build(model, 'newmtl m\nKs 0.9 0.9 0.9\nillum 1\n')).specular == 0.0

    def test_optical_density_is_the_index_of_refraction(self, model: str) -> None:
        assert physical(build(model, 'newmtl m\nNi 1.33\n')).ior == pytest.approx(1.33)

    def test_an_index_of_one_is_left_at_the_default(self, model: str) -> None:
        # Ni 1 is what exporters write for "unset", and an index of 1 reflects nothing
        assert physical(build(model, 'newmtl m\nNi 1.0\n')).ior == pytest.approx(1.5)

    def test_extension_factors(self, model: str) -> None:
        material = physical(build(model, 'newmtl m\nPc 0.7\nPcr 0.2\nPs 0.4\naniso 0.5\nanisor 0.25\n'))
        assert material.clearcoat == pytest.approx(0.7)
        assert material.clearcoatRoughness == pytest.approx(0.2)
        assert list(material.sheenColor) == pytest.approx([0.4] * 3)
        assert material.anisotropyStrength == pytest.approx(0.5)
        assert material.anisotropyRotation == pytest.approx(0.25 * 2 * np.pi)


class TestOpacity:
    def test_an_opaque_material_is_opaque(self, model: str) -> None:
        appearance = build(model, 'newmtl m\nd 1\n')
        assert appearance.alphaMode == 'OPAQUE'
        assert physical(appearance).transparency == 0.0

    def test_dissolve_below_one_blends(self, model: str) -> None:
        appearance = build(model, 'newmtl m\nd 0.25\n')
        assert appearance.alphaMode == 'BLEND'
        assert physical(appearance).transparency == pytest.approx(0.75)

    def test_a_material_that_is_wholly_transparent_is_drawn_opaque_and_says_so(
            self, model: str, caplog: Any) -> None:
        # Tr 1 (or d 0) on a surface that has no opacity map draws nothing; the
        # file's author meant opaque, as Crane's dinoshade materials do.
        with caplog.at_level(logging.WARNING):
            appearance = build(model, 'newmtl skin\nKd 0.1 1 0.1\nTr 1.0\n')
        assert appearance.alphaMode == 'OPAQUE'
        assert physical(appearance).transparency == 0.0
        assert "'skin'" in caplog.text and 'transparent' in caplog.text

    def test_dissolve_zero_is_treated_the_same_way(self, model: str) -> None:
        assert build(model, 'newmtl m\nd 0\n').alphaMode == 'OPAQUE'

    def test_a_cutout_mask_makes_a_masked_material(self, model: str, tmp_path: Path) -> None:
        mask = np.zeros((4, 4), np.uint8)
        mask[:, 2:] = 255
        Image.fromarray(mask, 'L').save(tmp_path / 'leaf_mask.png')
        png(tmp_path / 'leaf.png', (0, 200, 0))
        appearance = build(model, 'newmtl m\nmap_Kd leaf.png\nmap_d leaf_mask.png\n')
        assert appearance.alphaMode == 'MASK'
        assert appearance.alphaCutoff == pytest.approx(0.5)
        base = physical(appearance).baseTexture
        assert isinstance(base, ImageDataTexture)
        assert base.image.mode == 'RGBA'

    def test_the_mask_lands_on_the_right_texels(self, model: str, tmp_path: Path) -> None:
        # Opaque in the left half of the file: after the flip to v-up the same
        # half of each row is still opaque, and the top row of the file is the
        # bottom row of the image data.
        mask = np.zeros((4, 4), np.uint8)
        mask[0, :] = 255
        Image.fromarray(mask, 'L').save(tmp_path / 'mask.png')
        png(tmp_path / 'leaf.png')
        image = physical(build(model, 'newmtl m\nmap_Kd leaf.png\nmap_d mask.png\n')).baseTexture.image
        assert image.getpixel((0, 3))[3] == 255
        assert image.getpixel((0, 0))[3] == 0

    def test_a_mask_with_no_diffuse_map_makes_a_white_base_texture(self, model: str, tmp_path: Path) -> None:
        Image.fromarray(np.tile(np.array([[0, 255]], np.uint8), (4, 2)), 'L').save(tmp_path / 'm.png')
        material = physical(build(model, 'newmtl m\nKd 0.5 0.5 0.5\nmap_d m.png\n'))
        assert material.baseTexture.image.getpixel((0, 0))[:3] == (255, 255, 255)

    def test_a_gradient_mask_blends(self, model: str, tmp_path: Path) -> None:
        ramp = np.tile(np.linspace(0, 255, 16, dtype=np.uint8), (16, 1))
        Image.fromarray(ramp, 'L').save(tmp_path / 'ramp.png')
        assert build(model, 'newmtl m\nmap_d ramp.png\n').alphaMode == 'BLEND'

    def test_an_opaque_mask_changes_nothing(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'white.png', (255, 255, 255))
        appearance = build(model, 'newmtl m\nmap_d white.png\n')
        assert appearance.alphaMode == 'OPAQUE'

    def test_map_d_naming_the_diffuse_file_uses_its_alpha(self, model: str, tmp_path: Path) -> None:
        image = np.zeros((4, 4, 4), np.uint8)
        image[..., 0] = 255
        image[:, :2, 3] = 255
        Image.fromarray(image, 'RGBA').save(tmp_path / 'both.png')
        appearance = build(model, 'newmtl m\nmap_Kd both.png\nmap_d both.png\n')
        assert appearance.alphaMode == 'MASK'
        # the file's own alpha is the mask, so the texture is the file itself
        assert isinstance(physical(appearance).baseTexture, ImageTexture)
        assert physical(appearance).baseTexture.url[0].endswith('both.png')


class TestTextures:
    def test_diffuse_map_replaces_the_diffuse_colour(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'brick.png')
        material = physical(build(model, 'newmtl m\nKd 0.5 0.5 0.5\nmap_Kd brick.png\n'))
        assert isinstance(material.baseTexture, ImageTexture)
        assert material.baseTexture.url[0].endswith('brick.png')
        assert list(material.baseColor) == pytest.approx([1, 1, 1])

    def test_a_missing_map_leaves_the_colour_and_says_so(self, model: str, caplog: Any) -> None:
        with caplog.at_level(logging.WARNING):
            material = physical(build(model, 'newmtl m\nKd 0.5 0.25 0.1\nmap_Kd gone.png\n'))
        assert not material.baseTexture
        assert list(material.baseColor) == pytest.approx([0.5, 0.25, 0.1])
        assert 'gone.png' in caplog.text

    def test_a_texture_in_a_subdirectory(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'maps' / 'brick.png')
        material = physical(build(model, 'newmtl m\nmap_Kd maps/brick.png\n'))
        assert material.baseTexture.url[0].endswith('maps/brick.png')

    def test_backslashes_in_a_path_are_separators(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'maps' / 'brick.png')
        material = physical(build(model, 'newmtl m\nmap_Kd maps\\brick.png\n'))
        assert material.baseTexture.url[0].endswith('maps/brick.png')

    def test_a_name_in_the_wrong_case_finds_the_file(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'Maps' / 'Brick.PNG')
        material = physical(build(model, 'newmtl m\nmap_Kd maps/brick.png\n'))
        assert material.baseTexture.url[0].endswith('Maps/Brick.PNG')

    def test_an_absolute_path_from_another_machine_falls_back_to_the_file_name(
            self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'brick.png')
        material = physical(build(model, 'newmtl m\nmap_Kd C:\\Users\\artist\\textures\\brick.png\n'))
        assert material.baseTexture.url[0].endswith('brick.png')

    def test_a_path_out_of_the_models_directory_is_refused(self, model: str, tmp_path: Path, caplog: Any) -> None:
        outside = tmp_path.parent / 'outside.png'
        png(outside)
        with caplog.at_level(logging.WARNING):
            material = physical(build(model, 'newmtl m\nmap_Kd ../outside.png\n'))
        assert not material.baseTexture
        assert 'outside.png' in caplog.text

    def test_a_texture_is_found_beside_its_library_first(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'mats' / 'brick.png', (1, 2, 3))
        png(tmp_path / 'brick.png', (9, 9, 9))
        material = physical(build(model, 'newmtl m\nmap_Kd brick.png\n', directory='mats'))
        assert material.baseTexture.url[0].endswith('mats/brick.png')

    def test_a_texture_the_library_directory_lacks_is_found_beside_the_model(
            self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'mats').mkdir()
        png(tmp_path / 'brick.png')
        material = physical(build(model, 'newmtl m\nmap_Kd brick.png\n', directory='mats'))
        assert material.baseTexture.url[0].endswith('/brick.png')
        assert not material.baseTexture.url[0].endswith('mats/brick.png')

    def test_clamp_stops_the_repeat(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'a.png')
        texture = physical(build(model, 'newmtl m\nmap_Kd -clamp on a.png\n')).baseTexture
        assert texture.repeatS is False and texture.repeatT is False
        texture = physical(build(model, 'newmtl m\nmap_Kd a.png\n')).baseTexture
        assert texture.repeatS is True and texture.repeatT is True

    def test_scale_and_offset_become_a_texture_transform(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'a.png')
        appearance = build(model, 'newmtl m\nmap_Kd -s 2 3 1 -o 0.5 0.25 0 a.png\n')
        material = physical(appearance)
        transforms = appearance.textureTransform.textureTransform
        assert len(transforms) == 1
        assert material.baseTextureMapping == transforms[0].mapping
        matrix = np.asarray(transforms[0].matrix)
        assert matrix[0, 0] == pytest.approx(2) and matrix[1, 1] == pytest.approx(3)
        assert matrix[0, 3] == pytest.approx(0.5) and matrix[1, 3] == pytest.approx(0.25)

    def test_maps_with_the_same_transform_share_it(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'a.png')
        png(tmp_path / 'b.png')
        appearance = build(model, 'newmtl m\nmap_Kd -s 2 2 1 a.png\nmap_Ke -s 2 2 1 b.png\n')
        assert len(appearance.textureTransform.textureTransform) == 1

    def test_a_map_with_no_transform_needs_no_mapping(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'a.png')
        appearance = build(model, 'newmtl m\nmap_Kd a.png\n')
        assert not appearance.textureTransform
        assert physical(appearance).baseTextureMapping == ''

    def test_emission_map(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'glow.png')
        material = physical(build(model, 'newmtl m\nKe 0 0 0\nmap_Ke glow.png\n'))
        assert material.emissiveTexture.url[0].endswith('glow.png')
        assert list(material.emissiveColor) == pytest.approx([1, 1, 1])

    def test_a_normal_map(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'n.png', (128, 128, 255))
        material = physical(build(model, 'newmtl m\nnorm n.png\n'))
        assert isinstance(material.normalTexture, ImageTexture)

    def test_a_normal_map_in_the_bump_slot_is_used_as_one(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'n.png', (128, 128, 255))
        material = physical(build(model, 'newmtl m\nmap_Bump -bm 0.5 n.png\n'))
        assert isinstance(material.normalTexture, ImageTexture)
        assert material.normalScale == pytest.approx(0.5)

    def test_a_height_map_in_the_bump_slot_becomes_a_normal_map(self, model: str, tmp_path: Path) -> None:
        ramp = np.tile(np.linspace(0, 255, 16, dtype=np.uint8), (16, 1))
        Image.fromarray(ramp, 'L').save(tmp_path / 'height.png')
        material = physical(build(model, 'newmtl m\nbump height.png\n'))
        assert isinstance(material.normalTexture, ImageDataTexture)
        red = material.normalTexture.image.getpixel((8, 8))[0]
        assert red < 128

    def test_roughness_and_metallic_maps_pack_into_one_texture(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'rough.png', (64, 64, 64))
        png(tmp_path / 'metal.png', (191, 191, 191))
        material = physical(build(model, 'newmtl m\nmap_Pr rough.png\nmap_Pm metal.png\n'))
        pixel = material.metallicRoughnessTexture.image.getpixel((1, 1))
        assert pixel[1] == pytest.approx(64, abs=1) and pixel[2] == pytest.approx(191, abs=1)
        assert material.roughness == pytest.approx(1.0) and material.metallic == pytest.approx(1.0)

    def test_a_roughness_map_with_a_factor_scales_by_it(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'rough.png', (255, 255, 255))
        material = physical(build(model, 'newmtl m\nPr 0.4\nmap_Pr rough.png\n'))
        assert material.roughness == pytest.approx(0.4)

    def test_a_roughness_map_alone_leaves_metallic_at_its_factor(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'rough.png', (64, 64, 64))
        material = physical(build(model, 'newmtl m\nPm 0.5\nmap_Pr rough.png\n'))
        assert material.metallic == pytest.approx(0.5)
        assert material.metallicRoughnessTexture.image.getpixel((0, 0))[2] == 255

    def test_a_shininess_map_is_a_gloss_map(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'gloss.png', (255, 255, 255))
        material = physical(build(model, 'newmtl m\nmap_Ns gloss.png\n'))
        assert material.metallicRoughnessTexture.image.getpixel((0, 0))[1] == 0

    def test_clearcoat_maps(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'c.png')
        png(tmp_path / 'cr.png')
        material = physical(build(model, 'newmtl m\nPc 1\nmap_Pc c.png\nmap_Pcr cr.png\n'))
        assert material.clearcoatTexture.url[0].endswith('c.png')
        assert material.clearcoatRoughnessTexture.url[0].endswith('cr.png')

    def test_ambient_reflection_and_displacement_are_not_used(self, model: str, tmp_path: Path) -> None:
        for name in ('a', 'r', 'd'):
            png(tmp_path / (name + '.png'))
        appearance = build(model, 'newmtl m\nmap_Ka a.png\nrefl r.png\ndisp d.png\n')
        assert not physical(appearance).baseTexture
        assert not physical(appearance).occlusionTexture

    def test_one_file_is_one_texture_node_across_materials(self, model: str, tmp_path: Path) -> None:
        png(tmp_path / 'shared.png')
        library = parse_mtl('newmtl a\nmap_Kd shared.png\nnewmtl b\nmap_Kd shared.png\n', 'test.mtl')
        builder = MaterialBuilder(model)
        first, second = (builder.appearance(LibraryMaterial(item, '')) for item in library.values())
        assert physical(first).baseTexture is physical(second).baseTexture

    def test_unreadable_image_leaves_the_property_unmapped(self, model: str, tmp_path: Path, caplog: Any) -> None:
        (tmp_path / 'broken.png').write_bytes(b'not a png')
        with caplog.at_level(logging.WARNING):
            appearance = build(model, 'newmtl m\nKd 0.3 0.3 0.3\nmap_d broken.png\n')
        assert appearance.alphaMode == 'OPAQUE'
        assert 'broken.png' in caplog.text


class TestDefaults:
    def test_the_default_material_is_grey_and_shared(self, model: str) -> None:
        builder = MaterialBuilder(model)
        assert builder.default() is builder.default()
        assert list(physical(builder.default()).baseColor) == pytest.approx([0.8] * 3)

    def test_the_default_under_vertex_colours_is_white(self, model: str) -> None:
        assert list(physical(MaterialBuilder(model).default(coloured=True)).baseColor) == pytest.approx([1] * 3)


class TestLibraries:
    def test_a_library_beside_the_model(self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'model.mtl').write_text('newmtl red\nKd 1 0 0\n')
        found = load_libraries(['model.mtl'], model)
        assert list(found) == ['red']
        assert found['red'].directory == ''

    def test_a_library_in_a_subdirectory_knows_its_directory(self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'mats').mkdir()
        (tmp_path / 'mats' / 'model.mtl').write_text('newmtl red\nKd 1 0 0\n')
        assert load_libraries(['mats/model.mtl'], model)['red'].directory == 'mats'

    def test_a_name_with_spaces(self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'my materials.mtl').write_text('newmtl red\nKd 1 0 0\n')
        assert list(load_libraries(['my materials.mtl'], model)) == ['red']

    def test_several_libraries_on_one_line(self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'a.mtl').write_text('newmtl a\n')
        (tmp_path / 'b.mtl').write_text('newmtl b\n')
        assert list(load_libraries(['a.mtl b.mtl'], model)) == ['a', 'b']

    def test_the_later_library_wins_a_name(self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'a.mtl').write_text('newmtl m\nKd 1 0 0\n')
        (tmp_path / 'b.mtl').write_text('newmtl m\nKd 0 1 0\n')
        assert load_libraries(['a.mtl', 'b.mtl'], model)['m'].material.diffuse == pytest.approx((0, 1, 0))

    def test_a_library_in_the_wrong_case(self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'Model.MTL').write_text('newmtl red\n')
        assert list(load_libraries(['model.mtl'], model)) == ['red']

    def test_an_absolute_path_from_another_machine_falls_back_to_the_file_name(
            self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'model.mtl').write_text('newmtl red\n')
        assert list(load_libraries(['C:\\models\\model.mtl'], model)) == ['red']

    def test_a_missing_library_is_a_warning(self, model: str, caplog: Any) -> None:
        with caplog.at_level(logging.WARNING):
            assert load_libraries(['gone.mtl'], model) == {}
        assert 'gone.mtl' in caplog.text

    def test_a_missing_library_with_spaces_in_its_name_is_one_warning(self, model: str, caplog: Any) -> None:
        with caplog.at_level(logging.WARNING):
            assert load_libraries(['Mustang 13.04.2021 Compressed.mtl'], model) == {}
        assert [record.getMessage().split("'")[1] for record in caplog.records] == [
            'Mustang 13.04.2021 Compressed.mtl']

    def test_a_missing_library_among_several_is_named_alone(
            self, model: str, tmp_path: Path, caplog: Any) -> None:
        (tmp_path / 'a.mtl').write_text('newmtl a\n')
        with caplog.at_level(logging.WARNING):
            assert list(load_libraries(['a.mtl gone.mtl'], model)) == ['a']
        assert [record.getMessage().split("'")[1] for record in caplog.records] == ['gone.mtl']

    def test_a_library_outside_the_models_directory_is_refused(self, model: str, tmp_path: Path, caplog: Any) -> None:
        (tmp_path.parent / 'outside.mtl').write_text('newmtl red\n')
        with caplog.at_level(logging.WARNING):
            assert load_libraries(['../outside.mtl'], model) == {}

    def test_a_malformed_library_raises_naming_it(self, model: str, tmp_path: Path) -> None:
        (tmp_path / 'bad.mtl').write_text('newmtl m\nKd 1 x 0\n')
        with pytest.raises(ValueError, match=r'bad\.mtl:2'):
            load_libraries(['bad.mtl'], model)
