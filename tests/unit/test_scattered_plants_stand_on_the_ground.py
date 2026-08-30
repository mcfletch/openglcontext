"""A scattered plant stands on the ground, whatever it was modelled around.

Every instanced vegetation path in the engine agrees where a plant meets the
ground: the instance position is the contact point and the plant grows up from
it. The GPU nodes carry that in their vertex data -- a billboard quad spans
``y`` in ``[0, 1]``, :func:`load_clump_glb` rebases a clump to ``y = 0``, the
tree meshes are authored with their trunk foot at the origin -- so a card and a
clump and a tree all meet the ground the same way.

The scenegraph scatter takes a node instead of an array, and a node is modelled
around whatever its author chose. VRML's primitives are centred on their origin,
so a ``Cone`` used straight as a shrub is planted half its height into the hill
with its tip showing. Seating measures what the prototype occupies and lifts it
by its own underside, which puts the same contact point on it that the GPU nodes
already have and leaves a prototype already built on the ground untouched.
"""
import numpy as np
import pytest

from OpenGLContext.loaders import assets
from OpenGLContext.loaders.tiles3d.scatter import Scatter
from OpenGLContext.loaders.tiles3d.vegetation import (
    bush, conifer, grass_tuft, group_from_scatter,
)
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, Cone, Cylinder, Material, Shape, Sphere,
)
from OpenGLContext.scenegraph.group import Group
from OpenGLContext.scenegraph.transform import Transform


def _placements(positions=((0.0, 12.0, 0.0),), scale=1.0):
    """One placement per position, all facing the same way at one scale."""
    points = np.asarray(positions, 'f4').reshape(-1, 3)
    return Scatter(points, np.zeros(len(points)), np.full(len(points), scale))


def _shrub(height=8.0):
    """A cone used as a shrub -- centred on its origin, as VRML defines it."""
    return Shape(geometry=Cone(bottomRadius=2.5, height=height),
                 appearance=Appearance(material=Material()))


def _foot(group, index=0):
    """The world height of the lowest point of one instance in a scattered group."""
    low, _high = assets.bounds(group.children[index])
    return float(low[1])


class TestMeasuringAPrototype:
    """:func:`assets.bounds` is what seating asks where a prototype's underside is."""

    def test_a_primitive_is_the_box_vrml_gives_it(self) -> None:
        low, high = assets.bounds(Shape(geometry=Box(size=(1.0, 2.0, 3.0))))
        assert np.allclose(low, (-0.5, -1.0, -1.5))
        assert np.allclose(high, (0.5, 1.0, 1.5))

    @pytest.mark.parametrize('geometry,half_height', [
        (Cone(bottomRadius=2.5, height=8.0), 4.0),
        (Sphere(radius=1.5), 1.5),
        (Cylinder(radius=0.4, height=3.0), 1.5),
    ])
    def test_every_primitive_can_be_measured(self, geometry, half_height) -> None:
        """A geometry with no vertex array of its own still occupies a box."""
        low, high = assets.bounds(Shape(geometry=geometry))
        assert float(low[1]) == pytest.approx(-half_height)
        assert float(high[1]) == pytest.approx(half_height)

    def test_a_transform_moves_what_it_holds(self) -> None:
        measured = assets.bounds(Transform(translation=[0.0, 4.0, 0.0],
                                           children=[_shrub()]))
        assert float(measured[0][1]) == pytest.approx(0.0)
        assert float(measured[1][1]) == pytest.approx(8.0)

    def test_a_group_spans_all_of_its_parts(self) -> None:
        measured = assets.bounds(Group(children=[
            Transform(translation=[0.0, 1.0, 0.0],
                      children=[Shape(geometry=Sphere(radius=0.5))]),
            Transform(translation=[0.0, 5.0, 0.0],
                      children=[Shape(geometry=Sphere(radius=0.5))]),
        ]))
        assert float(measured[0][1]) == pytest.approx(0.5)
        assert float(measured[1][1]) == pytest.approx(5.5)

    def test_nothing_to_measure_says_so(self) -> None:
        assert assets.bounds(Group(children=[])) is None


class TestSeating:
    def test_a_centred_prototype_is_planted_on_the_surface(self) -> None:
        """The whole point: a bare cone stands on the ground instead of in it."""
        group = group_from_scatter(_placements(), _shrub())
        assert _foot(group) == pytest.approx(12.0)

    def test_it_grows_up_from_there(self) -> None:
        group = group_from_scatter(_placements(), _shrub(height=8.0))
        _low, high = assets.bounds(group.children[0])
        assert float(high[1]) == pytest.approx(20.0)

    def test_a_prototype_already_on_the_ground_is_left_alone(self) -> None:
        """The library's own prototypes are built foot-at-origin and must not move."""
        for prototype in (conifer(height=9.0), bush(size=1.3), grass_tuft(height=0.55)):
            group = group_from_scatter(_placements(), prototype)
            assert _foot(group) == pytest.approx(12.0, abs=1e-6)

    def test_a_scaled_instance_is_seated_by_its_scaled_underside(self) -> None:
        """The lift rides inside the instance scale, or a big shrub sinks further."""
        group = group_from_scatter(_placements(scale=2.5), _shrub(height=8.0))
        low, high = assets.bounds(group.children[0])
        assert float(low[1]) == pytest.approx(12.0)
        assert float(high[1]) == pytest.approx(12.0 + 20.0)

    def test_every_instance_is_seated(self) -> None:
        ground = [(0.0, 3.0, 0.0), (10.0, -7.5, 4.0), (-6.0, 21.25, -2.0)]
        group = group_from_scatter(_placements(ground), _shrub())
        for index, (_x, y, _z) in enumerate(ground):
            assert _foot(group, index) == pytest.approx(y)

    def test_a_caller_can_keep_the_origin_as_the_contact_point(self) -> None:
        """A prototype deliberately modelled about its middle says so and is left."""
        group = group_from_scatter(_placements(), _shrub(height=8.0), seat=False)
        assert _foot(group) == pytest.approx(8.0)

    def test_an_unmeasurable_prototype_is_placed_rather_than_refused(self) -> None:
        """Nothing to measure is not an error: it is a node with no extent yet."""
        group = group_from_scatter(_placements(), Group(children=[]))
        assert len(group.children) == 1

    def test_the_prototype_is_still_shared_by_every_instance(self) -> None:
        """Instancing collapses the scatter into one draw only while it is one node."""
        prototype = _shrub()
        group = group_from_scatter(_placements([(0.0, 0.0, 0.0)] * 5), prototype)
        seated = {id(child.children[0]) for child in group.children}
        assert len(seated) == 1

    def test_the_prototype_itself_is_not_moved(self) -> None:
        """Seating is a wrapper: the caller's node is theirs, and may be reused."""
        prototype = _shrub()
        group_from_scatter(_placements(), prototype)
        assert assets.bounds(prototype)[0][1] == pytest.approx(-4.0)


class TestSeatingOnRealGround:
    def test_a_disc_of_shrubs_meets_a_hillside(self) -> None:
        """End to end: scatter over a height field, and every foot is on it."""
        from OpenGLContext.loaders.tiles3d.vegetation import scatter_disc
        from OpenGLContext.scenegraph.terrain import HeightField

        def hilly(x, z):
            return 18.0 * np.sin(np.asarray(x, 'd') / 30.0) \
                + 11.0 * np.cos(np.asarray(z, 'd') / 22.0)

        field = HeightField.from_function(hilly, res=65, extent=400.0)
        placements = scatter_disc((0.0, 0.0, 0.0), 120.0, 0.004, seed=2,
                                  height_fn=field.sample, water_level=-1e9)
        assert len(placements) > 50
        group = group_from_scatter(placements, _shrub())
        feet = np.array([_foot(group, index) for index in range(len(placements))])
        ground = np.asarray(field.sample(placements.positions[:, 0],
                                         placements.positions[:, 2]), 'd')
        assert np.abs(feet - ground).max() < 1e-4


if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-v']))
