"""The MTL parser: material libraries into :class:`MtlMaterial` records, no GL.

Covers the classic Phong statements, the PBR extensions (Pr, Pm and the rest of
Exocortex's and Blender's additions), every texture map and the option flags
that may precede a map's file name.
"""
from __future__ import annotations

import pytest

from OpenGLContext.loaders.mtlfile import MtlMaterial, parse_mtl


def one(text: str) -> MtlMaterial:
    found = parse_mtl(text, 'test.mtl')
    assert len(found) == 1, found
    return next(iter(found.values()))


class TestColours:
    def test_each_colour_statement_reads_three_numbers(self) -> None:
        material = one('newmtl m\nKa 0.1 0.2 0.3\nKd 0.4 0.5 0.6\nKs 0.7 0.8 0.9\nKe 1 0.5 0\n')
        assert material.ambient == pytest.approx((0.1, 0.2, 0.3))
        assert material.diffuse == pytest.approx((0.4, 0.5, 0.6))
        assert material.specular == pytest.approx((0.7, 0.8, 0.9))
        assert material.emissive == pytest.approx((1, 0.5, 0))

    def test_one_number_is_a_grey(self) -> None:
        assert one('newmtl m\nKd 0.25\n').diffuse == pytest.approx((0.25, 0.25, 0.25))

    def test_xyz_colour_is_converted_to_rgb(self) -> None:
        # D65 white point in CIE XYZ is white in sRGB
        white = one('newmtl m\nKd xyz 0.9505 1.0 1.089\n').diffuse
        assert white == pytest.approx((1, 1, 1), abs=0.01)

    def test_a_spectral_colour_is_counted_and_left_unset(self) -> None:
        library = parse_mtl('newmtl m\nKd spectral curve.rfl\n', 'test.mtl')
        assert library['m'].diffuse is None
        assert library.ignored['Kd spectral'] == 1

    def test_a_material_that_states_no_colour_has_none(self) -> None:
        material = one('newmtl m\n')
        assert material.diffuse is None and material.specular is None and material.emissive is None


class TestScalars:
    def test_shininess(self) -> None:
        assert one('newmtl m\nNs 96.5\n').shininess == pytest.approx(96.5)

    def test_dissolve_is_the_opacity(self) -> None:
        assert one('newmtl m\nd 0.25\n').opacity == pytest.approx(0.25)

    def test_tr_is_the_transparency(self) -> None:
        assert one('newmtl m\nTr 0.25\n').opacity == pytest.approx(0.75)

    def test_dissolve_with_the_halo_flag(self) -> None:
        assert one('newmtl m\nd -halo 0.4\n').opacity == pytest.approx(0.4)

    def test_the_later_of_d_and_tr_wins(self) -> None:
        assert one('newmtl m\nd 0.5\nTr 0.1\n').opacity == pytest.approx(0.9)
        assert one('newmtl m\nTr 0.1\nd 0.5\n').opacity == pytest.approx(0.5)

    def test_optical_density_and_illumination(self) -> None:
        material = one('newmtl m\nNi 1.45\nillum 2\n')
        assert material.ior == pytest.approx(1.45)
        assert material.illum == 2

    @pytest.mark.parametrize('statement, field', [
        ('Pr 0.3', 'roughness'), ('Pm 0.9', 'metallic'), ('Ps 0.2', 'sheen'),
        ('Pc 0.7', 'clearcoat'), ('Pcr 0.1', 'clearcoat_roughness'),
        ('aniso 0.5', 'anisotropy'), ('anisor 0.25', 'anisotropy_rotation'),
    ])
    def test_the_pbr_extension_statements(self, statement: str, field: str) -> None:
        value = float(statement.split()[1])
        assert getattr(one('newmtl m\n' + statement + '\n'), field) == pytest.approx(value)

    def test_keywords_are_read_in_any_case(self) -> None:
        material = one('newmtl m\nKD 0.1 0.2 0.3\nns 5\nPR 0.5\n')
        assert material.diffuse == pytest.approx((0.1, 0.2, 0.3))
        assert material.shininess == 5
        assert material.roughness == 0.5


class TestMaps:
    @pytest.mark.parametrize('statement, channel', [
        ('map_Kd', 'diffuse'), ('map_Ka', 'ambient'), ('map_Ks', 'specular'),
        ('map_Ke', 'emissive'), ('map_Ns', 'shininess'), ('map_d', 'opacity'),
        ('map_Bump', 'bump'), ('map_bump', 'bump'), ('bump', 'bump'),
        ('norm', 'normal'), ('disp', 'displacement'), ('decal', 'decal'),
        ('refl', 'reflection'), ('map_Pr', 'roughness'), ('map_Pm', 'metallic'),
        ('map_Ps', 'sheen'), ('map_Pc', 'clearcoat'), ('map_Pcr', 'clearcoat_roughness'),
        ('map_aniso', 'anisotropy'), ('map_anisor', 'anisotropy_rotation'),
    ])
    def test_each_map_statement_names_its_channel(self, statement: str, channel: str) -> None:
        material = one('newmtl m\n%s image.png\n' % statement)
        assert material.maps[channel].file == 'image.png'

    def test_a_map_has_neutral_defaults(self) -> None:
        texture = one('newmtl m\nmap_Kd a.png\n').maps['diffuse']
        assert texture.scale == (1.0, 1.0, 1.0)
        assert texture.offset == (0.0, 0.0, 0.0)
        assert texture.bump_multiplier == 1.0
        assert texture.clamp is False

    def test_scale_and_offset_options(self) -> None:
        texture = one('newmtl m\nmap_Kd -s 2 3 1 -o 0.5 0.25 a.png\n').maps['diffuse']
        assert texture.file == 'a.png'
        assert texture.scale == (2.0, 3.0, 1.0)
        assert texture.offset == (0.5, 0.25, 0.0)

    def test_scale_with_fewer_numbers_keeps_the_rest_at_default(self) -> None:
        texture = one('newmtl m\nmap_Kd -s 4 a.png\n').maps['diffuse']
        assert texture.scale == (4.0, 1.0, 1.0)
        texture = one('newmtl m\nmap_Kd -o 0.5 0.25 a.png\n').maps['diffuse']
        assert texture.offset == (0.5, 0.25, 0.0)

    def test_bump_multiplier(self) -> None:
        assert one('newmtl m\nmap_Bump -bm 0.4 n.png\n').maps['bump'].bump_multiplier == pytest.approx(0.4)

    def test_clamp(self) -> None:
        assert one('newmtl m\nmap_Kd -clamp on a.png\n').maps['diffuse'].clamp is True
        assert one('newmtl m\nmap_Kd -clamp off a.png\n').maps['diffuse'].clamp is False

    def test_range_and_channel_options(self) -> None:
        texture = one('newmtl m\nmap_d -imfchan m -mm 0.1 0.8 a.png\n').maps['opacity']
        assert texture.channel == 'm'
        assert (texture.base, texture.gain) == (pytest.approx(0.1), pytest.approx(0.8))

    def test_options_with_no_effect_here_are_read_past(self) -> None:
        texture = one('newmtl m\nmap_Kd -blendu off -blendv off -cc on -t 1 1 1 '
                      '-texres 512 a.png\n').maps['diffuse']
        assert texture.file == 'a.png'

    def test_a_file_name_with_spaces_is_the_rest_of_the_line(self) -> None:
        texture = one('newmtl m\nmap_Kd -s 2 2 2 brick colour.png\n').maps['diffuse']
        assert texture.file == 'brick colour.png'
        assert texture.scale == (2.0, 2.0, 2.0)

    def test_windows_separators_become_slashes(self) -> None:
        assert one('newmtl m\nmap_Kd maps\\brick.png\n').maps['diffuse'].file == 'maps/brick.png'

    def test_a_reflection_map_keeps_its_type(self) -> None:
        texture = one('newmtl m\nrefl -type sphere sky.png\n').maps['reflection']
        assert texture.file == 'sky.png'

    def test_a_map_with_no_file_is_skipped(self) -> None:
        material = one('newmtl m\nmap_Kd\nmap_Ks -s 2\n')
        assert material.maps == {}

    def test_a_flag_whose_numbers_are_missing_is_skipped(self) -> None:
        texture = one('newmtl m\nmap_Kd -s a.png\n').maps['diffuse']
        assert texture.file == 'a.png'
        assert texture.scale == (1.0, 1.0, 1.0)


class TestLibrary:
    def test_materials_come_back_by_name_in_file_order(self) -> None:
        library = parse_mtl('newmtl b\nKd 1 0 0\nnewmtl a\nKd 0 1 0\n', 'test.mtl')
        assert list(library) == ['b', 'a']

    def test_a_name_may_hold_spaces(self) -> None:
        library = parse_mtl('newmtl dark red\nKd 0.5 0 0\n', 'test.mtl')
        assert list(library) == ['dark red']

    def test_a_second_definition_replaces_the_first(self) -> None:
        library = parse_mtl('newmtl m\nKd 1 0 0\nnewmtl m\nKd 0 1 0\n', 'test.mtl')
        assert library['m'].diffuse == pytest.approx((0, 1, 0))

    def test_statements_before_newmtl_are_counted_and_dropped(self) -> None:
        library = parse_mtl('Kd 1 0 0\nnewmtl m\nKd 0 1 0\n', 'test.mtl')
        assert library['m'].diffuse == pytest.approx((0, 1, 0))
        assert library.ignored['Kd (before newmtl)'] == 1

    def test_comments_blank_lines_crlf_and_bom(self) -> None:
        text = b'\xef\xbb\xbf# library\r\n\r\nnewmtl m # name\r\nKd 1 0 0 # red\r\n'
        assert parse_mtl(text, 'test.mtl')['m'].diffuse == pytest.approx((1, 0, 0))

    def test_unknown_statements_are_counted(self) -> None:
        library = parse_mtl('newmtl m\nsharpness 60\nTf 1 1 1\nfrob 1\n', 'test.mtl')
        assert library.ignored['sharpness'] == 1
        assert library.ignored['frob'] == 1

    def test_an_empty_library(self) -> None:
        assert len(parse_mtl('', 'test.mtl')) == 0


class TestMalformed:
    def test_an_unreadable_number_names_its_line(self) -> None:
        with pytest.raises(ValueError, match=r'test\.mtl:3.*abc'):
            parse_mtl('newmtl m\nKd 1 0 0\nKs 0.5 abc 0\n', 'test.mtl')

    def test_a_colour_with_two_numbers_names_its_line(self) -> None:
        with pytest.raises(ValueError, match=r'test\.mtl:2'):
            parse_mtl('newmtl m\nKd 1 0\n', 'test.mtl')

    @pytest.mark.parametrize('value', ['nan', 'inf'])
    def test_a_scalar_that_is_not_finite_is_refused(self, value: str) -> None:
        with pytest.raises(ValueError, match=r'test\.mtl:2'):
            parse_mtl('newmtl m\nNs %s\n' % value, 'test.mtl')

    def test_a_statement_with_no_value_is_refused(self) -> None:
        with pytest.raises(ValueError, match=r'test\.mtl:2'):
            parse_mtl('newmtl m\nNs\n', 'test.mtl')
