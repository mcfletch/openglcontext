"""Warning signs: a post, a plate, and the symbol on it.

A generated road already knows what it is about to do -- the alignment carries
its own curvature and its own grade -- so what a sign says and where it belongs
are derivable rather than authored. What is here is the object: the post, the
plate standing on it, and the face painted on the plate.

The geometry is built at the origin facing the road, because there are tens of
signs in a world and they are placed by instancing one prototype rather than by
building one mesh each.
"""
import numpy as np
import pytest

from OpenGLContext.scenegraph.roadsigns import (
    WARNINGS,
    SignProfile,
    sign_material,
    sign_meshes,
    sign_texture,
)


class TestTheObject:
    def test_it_is_a_post_and_a_plate(self) -> None:
        assert set(sign_meshes('bend-left')) == {'post', 'plate'}

    def test_both_are_drawable(self) -> None:
        for mesh in sign_meshes('dip').values():
            assert len(mesh.positions) and len(mesh.indices)
            assert len(mesh.normals) == len(mesh.positions)

    def test_every_kind_builds(self) -> None:
        for kind in WARNINGS:
            assert set(sign_meshes(kind)) == {'post', 'plate'}

    def test_a_kind_nobody_has_heard_of_is_reported(self) -> None:
        with pytest.raises(ValueError):
            sign_meshes('unicorn-crossing')

    def test_it_stands_at_the_origin(self) -> None:
        post = sign_meshes('crest')['post']
        assert abs(float(post.positions[:, 0].mean())) < 0.01
        assert abs(float(post.positions[:, 2].mean())) < 0.01

    def test_its_foot_is_on_the_ground(self) -> None:
        post = sign_meshes('crest')['post']
        assert float(post.positions[:, 1].min()) == pytest.approx(0.0, abs=1e-6)


class TestWhatADriverSees:
    def test_the_plate_is_above_the_bonnet(self) -> None:
        """Low enough to read, high enough that a car does not clip it."""
        plate = sign_meshes('tunnel')['plate']
        assert float(plate.positions[:, 1].min()) > 1.5

    def test_it_is_the_size_it_was_asked_for(self) -> None:
        plate = sign_meshes('dip', SignProfile(plate_size=1.4))['plate']
        span = float(plate.positions[:, 0].max() - plate.positions[:, 0].min())
        assert span == pytest.approx(1.4, abs=0.01)

    def test_the_plate_faces_along_minus_z(self) -> None:
        """The prototype's frame: a placement turns it to face the traffic."""
        plate = sign_meshes('dip')['plate']
        span = float(plate.positions[:, 2].max() - plate.positions[:, 2].min())
        assert span < 0.2

    def test_the_post_is_slimmer_than_the_plate(self) -> None:
        built = sign_meshes('bend-right')
        assert float(np.ptp(built['post'].positions[:, 0])) \
            < float(np.ptp(built['plate'].positions[:, 0])) / 3.0


class TestTheFace:
    def test_a_plate_carries_its_own_picture(self) -> None:
        assert sign_texture('bend-left').size == (256, 256)

    def test_each_kind_is_told_apart(self) -> None:
        seen = {kind: sign_texture(kind, size=64).tobytes() for kind in WARNINGS}
        assert len(set(seen.values())) == len(WARNINGS)

    def test_a_left_bend_turns_left_and_a_right_one_right(self) -> None:
        """The symbol is read from the bottom: where its far end has got to is
        which way the road goes."""
        def turns(kind):
            found = _ink(sign_texture(kind, size=128))
            rows, columns = np.nonzero(found)
            return float(columns[rows < rows.min() + 12].mean()) / 128.0 - 0.5
        assert turns('bend-left') < -0.05 < 0.05 < turns('bend-right')

    def test_it_has_something_on_it(self) -> None:
        """A blank plate is a plate nobody reads."""
        assert int(_ink(sign_texture('junction', size=128)).sum()) > 200

    def test_the_symbol_stays_inside_the_face(self) -> None:
        """A triangle narrows towards its point, so a symbol sized to look
        right across the bottom runs off the sides at the top."""
        for kind in WARNINGS:
            found = np.asarray(sign_texture(kind, size=128))
            rows, columns = np.nonzero(
                (found[..., 3] > 200)
                & (np.abs(found[..., 0].astype(int) - 176) < 24)
                & (found[..., 1] < 70))                 # the red border
            assert len(rows), kind
            ink = np.nonzero(_ink(sign_texture(kind, size=128)))
            # No black on a border pixel: the face is where the symbol lives.
            assert not (set(zip(*ink, strict=True))
                        & set(zip(rows, columns, strict=True))), kind

    def test_the_corners_are_clear(self) -> None:
        """A triangular plate on a square texture: the corners are cut away."""
        found = np.asarray(sign_texture('dip', size=64))
        assert int(found[0, 0, 3]) == 0 and int(found[0, -1, 3]) == 0

    def test_the_material_carries_the_face(self) -> None:
        assert sign_material('crest').texture('baseColor') is not None

    def test_a_caller_may_supply_the_image(self) -> None:
        from OpenGLContext.loaders.gltf.writer import ExternalImage
        material = sign_material('crest', image=ExternalImage('signs/crest.png',
                                                              srgb=True))
        assert material.texture('baseColor').uri == 'signs/crest.png'

    def test_it_is_not_a_mirror(self) -> None:
        assert sign_material('dip').metallic == 0.0


class TestTheUnwrap:
    def test_the_plate_has_texture_coordinates(self) -> None:
        plate = sign_meshes('dip')['plate']
        assert plate.texcoords is not None
        assert len(plate.texcoords) == len(plate.positions)

    def test_they_stay_inside_the_image(self) -> None:
        found = np.asarray(sign_meshes('dip')['plate'].texcoords)
        assert found.min() >= -0.001 and found.max() <= 1.001

    def test_the_face_is_the_right_way_up(self) -> None:
        """The plate's top vertex reads the top of the image."""
        plate = sign_meshes('dip')['plate']
        top = int(np.argmax(plate.positions[:, 1]))
        assert float(plate.texcoords[top][1]) < 0.1


def _ink(image) -> np.ndarray:
    """Where the black symbol is: opaque, and darker than the red border."""
    found = np.asarray(image)
    return (found[..., 3] > 200) & (found[..., :3].max(axis=-1) < 60)


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
