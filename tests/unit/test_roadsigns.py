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
    sign_atlas,
    sign_material,
    sign_mesh,
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
        assert turns('bend-left') < -0.02 < 0.02 < turns('bend-right')

    def test_it_has_something_on_it(self) -> None:
        """A blank plate is a plate nobody reads."""
        assert int(_ink(sign_texture('junction', size=128)).sum()) > 200

    def test_the_symbol_stays_inside_the_face(self) -> None:
        """A diamond narrows towards all four of its corners, so a symbol sized
        to look right across its middle runs off it above and below.

        Nothing of the symbol touches the border: every pixel next to one of
        its own is either more symbol or plate face.
        """
        for kind in WARNINGS:
            image = sign_texture(kind, size=128)
            symbol, face = _ink(image), _face(image)
            assert symbol.any() and face.any(), kind
            assert not (_grown(symbol) & ~(symbol | face)).any(), kind

    def test_the_corners_are_clear(self) -> None:
        """A diamond on a square texture: the corners are cut away."""
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
    """Where the symbol is: the black *inside* the plate's face.

    The border is black as well, so colour alone does not tell the two apart.
    What does is that the symbol has face either side of it along its own row
    and the border does not.
    """
    found = np.asarray(image)
    black = (found[..., 3] > 200) & (found[..., :3].max(axis=-1) < 60)
    face = (found[..., 3] > 200) & ~black
    left = np.cumsum(face, axis=1) > 0
    right = np.cumsum(face[:, ::-1], axis=1)[:, ::-1] > 0
    return black & left & right


def _face(image) -> np.ndarray:
    """Where the plate's own colour is: opaque, and not the black legend."""
    found = np.asarray(image)
    black = (found[..., 3] > 200) & (found[..., :3].max(axis=-1) < 60)
    return (found[..., 3] > 200) & ~black


def _grown(mask: np.ndarray) -> np.ndarray:
    """The mask and every pixel touching it."""
    out = mask.copy()
    for axis in (0, 1):
        for step in (1, -1):
            out |= np.roll(mask, step, axis=axis)
    return out


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))


class TestThePlateCostsWhatAPlateCosts:
    """The plate is cut to its own outline, so the picture's transparent corners
    fall outside the geometry and never reach a fragment. Declared as a cutout
    anyway, every sign in a world joins the sorted alpha pass -- which is what a
    warning sign is not: a few hundred triangles of opaque painted metal."""

    def test_it_is_opaque(self) -> None:
        assert sign_material('dip').alphaMode == 'OPAQUE'

    def test_it_is_not_double_sided(self) -> None:
        """It has a back of its own; drawing both faces of both is waste."""
        assert not sign_material('dip').doubleSided

    def test_the_geometry_is_the_shape_the_picture_is(self) -> None:
        """A diamond of four corners, not a quad with the corners painted out."""
        plate = sign_meshes('dip')['plate']
        front = plate.positions[plate.positions[:, 2] < 0]
        assert len(front) == 4
        across = float(np.abs(front[:, 0]).max())
        # Its widest point is halfway up it, which a rectangle's is not.
        widest = front[np.abs(np.abs(front[:, 0]) - across) < 1e-6]
        assert float(widest[:, 1].mean()) == pytest.approx(
            float(front[:, 1].mean()))


class TestOneTextureForEveryKind:
    """Seven kinds of plate is seven textures, seven materials and seven draws
    for what is one object with a different picture on it. An atlas makes it one
    of each: the post and every plate live in one image, and which sign a piece
    of geometry is comes out of where it reads."""

    def test_the_atlas_holds_every_kind_it_was_asked_for(self) -> None:
        image, cells = sign_atlas(('dip', 'crest'))
        assert set(cells) >= {'dip', 'crest'}
        assert image.size[0] >= 256

    def test_each_kind_has_its_own_corner(self) -> None:
        _image, cells = sign_atlas(WARNINGS)
        boxes = [tuple(cells[kind]) for kind in WARNINGS]
        assert len(set(boxes)) == len(WARNINGS)

    def test_the_corners_are_inside_the_image(self) -> None:
        _image, cells = sign_atlas(WARNINGS)
        for box in cells.values():
            assert 0.0 <= min(box) and max(box) <= 1.0

    def test_the_post_reads_from_it_too(self) -> None:
        """One material for the whole sign, so it is one draw."""
        _image, cells = sign_atlas(('dip',))
        assert 'post' in cells

    def test_the_post_s_patch_is_a_flat_colour(self) -> None:
        import numpy as np
        image, cells = sign_atlas(('dip',))
        u0, v0, u1, v1 = cells['post']
        found = np.asarray(image.convert('RGB'), 'd')
        patch = found[int(v0 * image.height) + 2:int(v1 * image.height) - 2,
                      int(u0 * image.width) + 2:int(u1 * image.width) - 2]
        assert float(patch.reshape(-1, 3).std(axis=0).max()) < 2.0

    def test_the_same_kinds_make_the_same_atlas(self) -> None:
        first, _ = sign_atlas(WARNINGS)
        second, _ = sign_atlas(WARNINGS)
        assert first.tobytes() == second.tobytes()

    def test_a_kind_nobody_has_heard_of_is_reported(self) -> None:
        with pytest.raises(ValueError):
            sign_atlas(('unicorn-crossing',))


class TestASignAsOneMesh:
    def test_it_is_a_single_mesh(self) -> None:
        _image, cells = sign_atlas(('dip',))
        mesh = sign_mesh('dip', cells=cells)
        assert len(mesh.positions) and mesh.texcoords is not None

    def test_the_post_is_still_under_the_plate(self) -> None:
        _image, cells = sign_atlas(('dip',))
        mesh = sign_mesh('dip', cells=cells)
        assert float(mesh.positions[:, 1].min()) == pytest.approx(0.0, abs=1e-5)
        assert float(mesh.positions[:, 1].max()) > 2.0

    def test_the_plate_reads_its_own_corner_of_the_atlas(self) -> None:
        _image, cells = sign_atlas(WARNINGS)
        u0, v0, u1, v1 = cells['crest']
        found = np.asarray(sign_mesh('crest', cells=cells).texcoords)
        plate = found[(found[:, 0] >= u0 - 1e-6) & (found[:, 0] <= u1 + 1e-6)
                      & (found[:, 1] >= v0 - 1e-6) & (found[:, 1] <= v1 + 1e-6)]
        assert len(plate) >= 6

    def test_two_kinds_differ_only_in_where_they_read(self) -> None:
        """Which is what makes them one geometry with a different picture."""
        _image, cells = sign_atlas(WARNINGS)
        first = sign_mesh('dip', cells=cells)
        second = sign_mesh('crest', cells=cells)
        assert np.allclose(first.positions, second.positions)
        assert not np.allclose(first.texcoords, second.texcoords)

    def test_given_no_atlas_it_makes_one_for_the_kind_it_is(self) -> None:
        found = np.asarray(sign_mesh('dip').texcoords)
        assert 0.0 <= found.min() and found.max() <= 1.0
        assert len(np.unique(np.round(found, 4), axis=0)) > 1
