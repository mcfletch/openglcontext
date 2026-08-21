"""Signs to the Ontario pattern: a yellow diamond, a tab under it, a maximum.

What a warning sign *is* differs by country, and this one is Ontario's: a black
symbol on a yellow diamond, an advisory speed on a rectangular tab beneath it,
and a speed limit as a white rectangle reading MAXIMUM over the number. The
shape carries as much of the meaning as the symbol does -- a driver reads a
diamond as "take care" and a white rectangle as "this is the law" long before
they have read what is on it -- so the shapes are as much a part of this as the
colours.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.roadsigns import (
    LEGEND,
    REGULATORY_FACE,
    WARNING_FACE,
    WARNINGS,
    SignFace,
    SignProfile,
    sign_atlas,
    sign_mesh,
    sign_meshes,
    sign_texture,
)


def _face(image) -> np.ndarray:
    """Where the plate's own colour is, whatever that colour is."""
    found = np.asarray(image)
    return found[..., 3] > 200


def _painted(image, colour) -> np.ndarray:
    found = np.asarray(image).astype(int)
    return (found[..., 3] > 200) & (
        np.abs(found[..., :3] - np.asarray(colour[:3])).max(axis=-1) < 30)


class TestTheWarningPlate:
    """A diamond, in yellow, with a black border and a black symbol."""

    def test_it_is_a_diamond(self) -> None:
        """Four corners, on point: the widest row is halfway down it."""
        found = _face(sign_texture('dip', size=128))
        rows = np.nonzero(found.any(axis=1))[0]
        widths = found.sum(axis=1)[rows]
        assert abs(int(np.argmax(widths)) - len(rows) // 2) < len(rows) * 0.1

    def test_and_the_geometry_is_one_too(self) -> None:
        plate = sign_meshes('dip')['plate']
        front = plate.positions[plate.positions[:, 2] < 0]
        assert len(front) == 4

    def test_its_face_is_yellow(self) -> None:
        assert _painted(sign_texture('dip', size=128), WARNING_FACE).sum() > 1000

    def test_inside_a_black_border(self) -> None:
        image = sign_texture('dip', size=128)
        edge = _painted(image, LEGEND)
        assert edge.sum() > 200
        # The border is at the outside: the topmost painted row is border.
        rows = np.nonzero(_face(image).any(axis=1))[0]
        assert edge[rows[0]].any()

    def test_and_a_black_symbol_on_it(self) -> None:
        image = sign_texture('crest', size=128)
        ink = _painted(image, LEGEND)
        middle = ink[40:88, 40:88]
        assert middle.sum() > 40

    def test_the_corners_of_the_picture_are_clear(self) -> None:
        found = np.asarray(sign_texture('dip', size=64))
        assert int(found[0, 0, 3]) == 0 and int(found[0, -1, 3]) == 0

    def test_every_kind_still_says_something_of_its_own(self) -> None:
        seen = {kind: sign_texture(kind, size=64).tobytes() for kind in WARNINGS}
        assert len(set(seen.values())) == len(WARNINGS)


class TestTheSpeedLimit:
    """A white rectangle: MAXIMUM, the number, km/h."""

    def test_it_is_a_rectangle_standing_up(self) -> None:
        found = _face(sign_texture('limit-100', size=128))
        rows = np.nonzero(found.any(axis=1))[0]
        columns = np.nonzero(found.any(axis=0))[0]
        assert len(rows) > len(columns)

    def test_and_the_geometry_is_one_too(self) -> None:
        plate = sign_meshes(SignFace('limit', 100))['plate']
        front = plate.positions[plate.positions[:, 2] < 0]
        assert len(front) == 4

    def test_its_face_is_white(self) -> None:
        assert _painted(sign_texture('limit-100', size=128),
                        REGULATORY_FACE).sum() > 1000

    def test_it_carries_its_own_number(self) -> None:
        one = sign_texture('limit-100', size=128).tobytes()
        other = sign_texture('limit-80', size=128).tobytes()
        assert one != other

    def test_and_a_limit_is_told_from_an_advisory(self) -> None:
        assert (sign_texture('limit-60', size=128).tobytes()
                != sign_texture('advisory-60', size=128).tobytes())


class TestTheAdvisoryTab:
    """A yellow tab under the diamond, saying how fast the bend is worth."""

    def test_a_bend_with_a_speed_carries_two_plates(self) -> None:
        face = SignFace('bend-left', 60)
        assert face.plates == ('advisory-60', 'bend-left')

    def test_and_one_without_carries_the_diamond_alone(self) -> None:
        assert SignFace('bend-left').plates == ('bend-left',)

    def test_the_tab_is_wider_than_it_is_tall(self) -> None:
        found = _face(sign_texture('advisory-60', size=128))
        rows = np.nonzero(found.any(axis=1))[0]
        columns = np.nonzero(found.any(axis=0))[0]
        assert len(columns) > len(rows)

    def test_it_is_yellow_like_the_diamond_over_it(self) -> None:
        assert _painted(sign_texture('advisory-60', size=128),
                        WARNING_FACE).sum() > 300

    def test_and_it_stands_below_the_diamond(self) -> None:
        from OpenGLContext.scenegraph.roadsigns import ADVISORY_SHAPE
        profile = SignProfile()
        plate = sign_meshes(SignFace('bend-left', 60))['plate']
        heights = np.asarray(plate.positions)[:, 1]
        assert heights.min() == pytest.approx(profile.post_height)
        top = profile.post_height + ADVISORY_SHAPE[1] * profile.plate_size
        above = heights[heights > top + 1e-6]
        assert above.min() >= top + profile.plate_gap - 1e-6

    def test_and_the_post_reaches_the_top_of_it(self) -> None:
        mesh = sign_mesh(SignFace('bend-left', 60))
        assert mesh.positions[:, 1].min() == pytest.approx(0.0)

    def test_a_sign_with_a_tab_is_taller_than_one_without(self) -> None:
        assert (sign_mesh(SignFace('bend-left', 60)).positions[:, 1].max()
                > sign_mesh(SignFace('bend-left')).positions[:, 1].max())


class TestWhatASignIs:
    def test_a_plain_kind_is_still_a_sign(self) -> None:
        assert SignFace.of('dip') == SignFace('dip')

    def test_and_one_that_is_already_a_face_is_left_alone(self) -> None:
        face = SignFace('dip', 40)
        assert SignFace.of(face) is face

    def test_a_kind_nobody_has_heard_of_is_reported(self) -> None:
        with pytest.raises(ValueError):
            assert SignFace('hovercraft').plates

    def test_a_speed_limit_needs_a_speed(self) -> None:
        with pytest.raises(ValueError):
            assert SignFace('limit').plates


class TestOneImageForAllOfIt:
    def test_the_atlas_holds_every_plate_a_sign_needs(self) -> None:
        _image, cells = sign_atlas((SignFace('bend-left', 60),
                                    SignFace('limit', 100)))
        assert set(cells) >= {'bend-left', 'advisory-60', 'limit-100', 'post'}

    def test_and_a_sign_is_still_one_mesh(self) -> None:
        image, cells = sign_atlas((SignFace('bend-left', 60),))
        mesh = sign_mesh(SignFace('bend-left', 60), cells=cells)
        assert len(mesh.positions) and image.size[0] >= 256

    def test_every_plate_reads_inside_its_own_cell(self) -> None:
        _image, cells = sign_atlas((SignFace('bend-left', 60),))
        mesh = sign_mesh(SignFace('bend-left', 60), cells=cells)
        found = np.asarray(mesh.texcoords)
        assert found.min() >= -0.001 and found.max() <= 1.001


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
