"""X3D's RigidBodyPhysics: bodies, collidables, collisions and joints on omi_physics.

Documents are read as a user's are and their collections stepped by hand
(`RigidBodyCollection.advance`), so nothing here needs a window.
"""
import math

import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.loaders.x3d import prototypes
from OpenGLContext.physics import x3drigid

FRAME = 1.0 / 60.0

BALL = b'''<Group>
  <CollidableShape DEF="BALL-GEOM"><Shape containerField="shape"><Sphere radius="0.1"/></Shape>
  </CollidableShape>
  <CollidableShape DEF="GROUND-GEOM" translation="0 -0.5 0">
    <Shape containerField="shape"><Box size="20 0.1 20"/></Shape>
  </CollidableShape>
</Group>'''


def scene(body: bytes, head: bytes = b'') -> object:
    """The scene an X3D document of `body` builds"""
    return Loader.loads(b'<X3D version="4.0"><Scene>' + head + body + b'</Scene></X3D>',
                        'scene.x3d')


def run(collection, seconds: float, sensors=(), each=None) -> None:
    """Step `collection` a frame at a time, sensing between frames"""
    for _ in range(round(seconds / FRAME)):
        for sensor in sensors:
            sensor.sense()
        collection.advance(FRAME)
        if each is not None:
            each()


def falling(extra: bytes = b'', body: bytes = b'position="0 2 0"', collection: bytes = b'',
            inner: bytes = b''):
    return scene(BALL + b'''<RigidBodyCollection DEF="C" ''' + collection + b'''>
      <RigidBody DEF="B" containerField="bodies" ''' + body + b'''>''' + inner + b'''
        <CollidableShape USE="BALL-GEOM" containerField="geometry"/>
      </RigidBody></RigidBodyCollection>''' + extra)


class TestNodes:
    @pytest.mark.parametrize('name', [
        'RigidBodyCollection', 'RigidBody', 'CollidableShape', 'CollidableOffset',
        'CollisionCollection', 'CollisionSpace', 'CollisionSensor', 'Contact', 'BallJoint',
        'DoubleAxisHingeJoint', 'MotorJoint', 'SingleAxisHingeJoint', 'SliderJoint',
        'UniversalJoint'])
    def test_each_is_implemented(self, name):
        assert name in prototypes()

    def test_a_collidable_shape_draws_its_shape_where_it_is(self):
        from OpenGLContext.scenegraph import nodepath  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph.basenodes import Box, Shape, sceneGraph  # noqa: PLC0415 kept with its use
        shape = Shape(geometry=Box())
        collidable = prototypes()['CollidableShape'](shape=shape, translation=(1, 2, 3))
        assert collidable.renderedChildren() == [shape]
        graph = sceneGraph(children=[collidable])
        path = nodepath.NodePath([]) + graph + collidable + shape
        assert np.allclose(np.asarray(path.transformMatrix())[3, :3], (1, 2, 3))

    def test_a_collidable_offset_draws_what_it_holds(self):
        inner = prototypes()['CollidableShape']()
        offset = prototypes()['CollidableOffset'](collidable=inner, translation=(0, 1, 0))
        assert offset.renderedChildren() == [inner]
        assert prototypes()['CollidableOffset']().renderedChildren() == []

    def test_a_collidable_is_bounded_by_its_shape(self):
        from OpenGLContext.scenegraph.basenodes import Box, Shape  # noqa: PLC0415 kept with its use
        collidable = prototypes()['CollidableShape'](shape=Shape(geometry=Box(size=(2, 4, 6))))
        volume = collidable.boundingVolume(None)
        assert np.allclose(volume.getPoints()[:, :3].max(axis=0), (1, 2, 3))


class TestBodies:
    def test_a_body_falls_and_says_where_it_is(self):
        graph = falling()
        run(graph.getDEF('C'), 1.0)
        body = graph.getDEF('B')
        assert body.position[1] == pytest.approx(2.0 - 0.5 * 9.8, abs=0.1)
        assert body.linearVelocity[1] == pytest.approx(-9.8, abs=0.1)

    def test_the_collidables_are_carried(self):
        graph = falling()
        run(graph.getDEF('C'), 0.5)
        assert np.allclose(graph.getDEF('BALL-GEOM').translation, graph.getDEF('B').position)

    def test_a_transform_routed_from_the_body_follows_it(self):
        graph = falling(extra=b'''<Transform DEF="T"/>
          <ROUTE fromNode="B" fromField="position_changed" toNode="T" toField="translation"/>
          <ROUTE fromNode="B" fromField="orientation_changed" toNode="T" toField="rotation"/>''',
                        body=b'position="0 2 0" angularVelocity="0 0 1"')
        run(graph.getDEF('C'), 0.5)
        assert np.allclose(graph.getDEF('T').translation, graph.getDEF('B').position)
        assert graph.getDEF('T').rotation[3] == pytest.approx(0.5, abs=0.02)

    def test_the_collections_gravity(self):
        graph = falling(collection=b'gravity="1 0 0"')
        run(graph.getDEF('C'), 1.0)
        assert graph.getDEF('B').position[0] == pytest.approx(0.5, abs=0.05)

    def test_a_body_out_of_global_gravity_floats(self):
        graph = falling(body=b'position="0 2 0" useGlobalGravity="false"')
        run(graph.getDEF('C'), 1.0)
        assert np.allclose(graph.getDEF('B').position, (0, 2, 0))

    def test_a_body_taken_out_lets_its_collidables_go(self):
        graph = falling()
        collection, ball = graph.getDEF('C'), graph.getDEF('BALL-GEOM')
        run(collection, 0.1)
        assert x3drigid.carrier(ball) is graph.getDEF('B')
        graph.getDEF('B').enabled = False
        run(collection, 0.1)
        assert x3drigid.carrier(ball) is None

    def test_a_fixed_body_stays(self):
        graph = falling(body=b'position="0 2 0" fixed="true"')
        run(graph.getDEF('C'), 1.0)
        assert np.allclose(graph.getDEF('B').position, (0, 2, 0))

    def test_a_disabled_collection_does_nothing(self):
        graph = falling(collection=b'enabled="false"')
        run(graph.getDEF('C'), 1.0)
        assert np.allclose(graph.getDEF('B').position, (0, 2, 0))

    def test_a_body_set_moving_moves(self):
        graph = falling(body=b'position="0 2 0" useGlobalGravity="false" '
                             b'linearVelocity="1 0 0"')
        run(graph.getDEF('C'), 1.0)
        assert graph.getDEF('B').position[0] == pytest.approx(1.0, abs=0.02)

    def test_a_position_sent_to_a_body_puts_it_there(self):
        graph = falling(body=b'position="0 2 0" useGlobalGravity="false"')
        collection, body = graph.getDEF('C'), graph.getDEF('B')
        run(collection, 0.1)
        body.position = (3.0, 4.0, 5.0)
        run(collection, 0.1)
        assert np.allclose(body.position, (3, 4, 5))

    def test_a_velocity_sent_to_a_body_sets_it_going(self):
        graph = falling(body=b'position="0 2 0" useGlobalGravity="false"')
        collection, body = graph.getDEF('C'), graph.getDEF('B')
        run(collection, 0.1)
        body.linearVelocity = (0.0, 0.0, 2.0)
        run(collection, 0.5)
        assert body.position[2] == pytest.approx(1.0, abs=0.05)

    def test_forces_and_torques_push_each_frame(self):
        graph = falling(body=b'position="0 2 0" useGlobalGravity="false" mass="2" '
                             b'forces="1 0 0 1 0 0" torques="0 0.001 0"')
        run(graph.getDEF('C'), 1.0)
        body = graph.getDEF('B')
        assert body.linearVelocity[0] == pytest.approx(1.0, abs=0.02)
        assert body.angularVelocity[1] > 0.0

    def test_a_centre_of_mass_off_the_origin(self):
        """Turning half a turn about its mass carries the origin across it."""
        graph = falling(body=b'position="0 0 0" useGlobalGravity="false" '
                             b'centerOfMass="1 0 0" angularVelocity="0 0 3.14159265"')
        run(graph.getDEF('C'), 1.0)
        assert np.allclose(graph.getDEF('B').position, (2, 0, 0), atol=0.02)

    def test_the_inertia_given_is_the_inertia_used(self):
        light = falling(body=b'useGlobalGravity="false" torques="0 1 0" '
                              b'inertia="1 0 0 0 0.5 0 0 0 1"')
        run(light.getDEF('C'), 1.0)
        assert light.getDEF('B').angularVelocity[1] == pytest.approx(2.0, abs=0.02)

    def test_a_mass_density_model_gives_the_inertia(self):
        graph = falling(body=b'useGlobalGravity="false" torques="0 1 0" mass="1"',
                        inner=b'<Box containerField="massDensityModel" size="1 1 1"/>')
        run(graph.getDEF('C'), 1.0)
        assert graph.getDEF('B').angularVelocity[1] == pytest.approx(6.0, abs=0.05)

    def test_a_finite_rotation_turns_as_far_as_its_spin(self):
        graph = falling(body=b'useGlobalGravity="false" useFiniteRotation="true" '
                             b'angularVelocity="40 0 0" angularDampingFactor="0"')
        run(graph.getDEF('C'), 1.0)
        turn = graph.getDEF('B').orientation
        angle = turn[3] if turn[0] > 0 else -turn[3]
        assert math.remainder(angle - 40.0, 2 * math.pi) == pytest.approx(0.0, abs=1e-4)

    def test_bodies_rest_only_where_told_to(self):
        graph = falling(body=b'useGlobalGravity="false"')
        run(graph.getDEF('C'), 2.0)
        assert graph.getDEF('C').awake()
        graph = falling(body=b'useGlobalGravity="false" autoDisable="true" disableTime="0.1" '
                             b'disableLinearSpeed="0.1" disableAngularSpeed="0.1"')
        run(graph.getDEF('C'), 2.0)
        assert not graph.getDEF('C').awake()


class TestCollisions:
    def test_without_a_collider_nothing_collides(self):
        graph = falling(extra=b'')
        run(graph.getDEF('C'), 1.5)
        assert graph.getDEF('B').position[1] < -0.6

    def test_the_collider_collides_its_collidables(self):
        graph = scene(BALL + b'''<RigidBodyCollection DEF="C">
          <CollisionCollection containerField="collider" bounce="0">
            <CollidableShape USE="BALL-GEOM"/><CollidableShape USE="GROUND-GEOM"/>
          </CollisionCollection>
          <RigidBody DEF="B" containerField="bodies" position="0 2 0">
            <CollidableShape USE="BALL-GEOM" containerField="geometry"/>
          </RigidBody></RigidBodyCollection>''')
        run(graph.getDEF('C'), 2.0)
        assert graph.getDEF('B').position[1] == pytest.approx(-0.45 + 0.1, abs=0.02)

    def test_contacts_routed_to_the_collection_bounce_the_ball(self):
        graph = scene(BALL + b'''<RigidBodyCollection DEF="C">
          <RigidBody DEF="B" containerField="bodies" position="0 2 0">
            <CollidableShape USE="BALL-GEOM" containerField="geometry"/>
          </RigidBody></RigidBodyCollection>
          <CollisionSensor DEF="S">
            <CollisionCollection containerField="collider" bounce="1.0" minBounceSpeed="1.0">
              <CollidableShape USE="BALL-GEOM"/><CollidableShape USE="GROUND-GEOM"/>
            </CollisionCollection>
          </CollisionSensor>
          <ROUTE fromNode="S" fromField="contacts" toNode="C" toField="set_contacts"/>''')
        heights = []
        body = graph.getDEF('B')
        run(graph.getDEF('C'), 3.0, sensors=[graph.getDEF('S')],
            each=lambda: heights.append(body.position[1]))
        landed = heights.index(min(heights))
        assert min(heights) > -0.45
        assert max(heights[landed:]) > 1.0

    def test_a_contact_with_the_world_holds_the_body_up(self):
        graph = falling()
        collection, body = graph.getDEF('C'), graph.getDEF('B')
        contact_type = prototypes()['Contact']
        for _ in range(round(2.0 / FRAME)):
            if body.position[1] < 0.1:
                collection.set_contacts = [contact_type(
                    body1=body, geometry1=graph.getDEF('BALL-GEOM'), position=(0, 0, 0),
                    contactNormal=(0, -1, 0), depth=0.0)]
            collection.advance(FRAME)
        assert body.position[1] == pytest.approx(0.1, abs=0.03)

    def test_the_sensor_reports_contacts_and_intersections(self):
        graph = scene(BALL + b'''<CollisionSensor DEF="S">
            <CollisionCollection DEF="CC" containerField="collider" bounce="0.5"
              frictionCoefficients="0.3 0.2" appliedParameters='"BOUNCE" "FRICTION_COEFFICIENT-2"'>
              <CollidableShape USE="BALL-GEOM"/><CollidableShape USE="GROUND-GEOM"/>
            </CollisionCollection>
          </CollisionSensor>''')
        sensor, ball = graph.getDEF('S'), graph.getDEF('BALL-GEOM')
        ball.translation = (0.0, 0.0, 0.0)
        sensor.sense()
        assert sensor.isActive is False
        ball.translation = (0.0, -0.36, 0.0)
        sensor.sense()
        assert sensor.isActive is True
        assert set(sensor.intersections) == {ball, graph.getDEF('GROUND-GEOM')}
        contact = sensor.contacts[0]
        assert contact.depth == pytest.approx(0.01, abs=1e-3)
        assert abs(contact.contactNormal[1]) == pytest.approx(1.0)
        assert contact.bounce == pytest.approx(0.5)
        assert np.allclose(contact.frictionCoefficients, (0.3, 0.2))
        assert {contact.geometry1, contact.geometry2} == {ball, graph.getDEF('GROUND-GEOM')}
        ball.translation = (0.0, 0.0, 0.0)
        sensor.sense()
        assert sensor.isActive is False
        assert len(sensor.contacts) == 0

    def test_a_space_without_geometry_collides_by_bounds(self):
        graph = scene(b'''<CollidableShape DEF="A" translation="0.9 0.9 0">
            <Shape containerField="shape"><Sphere radius="0.5"/></Shape></CollidableShape>
          <CollidableShape DEF="BOX"><Shape containerField="shape"><Box size="1 1 1"/></Shape>
          </CollidableShape>
          <CollisionSensor DEF="S"><CollisionCollection containerField="collider">
            <CollisionSpace DEF="SPACE" useGeometry="false">
              <CollidableShape USE="A"/><CollidableShape USE="BOX"/>
            </CollisionSpace></CollisionCollection></CollisionSensor>''')
        sensor = graph.getDEF('S')
        sensor.sense()
        assert sensor.isActive is True
        graph.getDEF('SPACE').useGeometry = True
        sensor.sense()
        assert sensor.isActive is False


class TestGeometry:
    @pytest.mark.parametrize('geometry,kind', [
        (b'<Box size="1 2 3"/>', 'box'), (b'<Sphere radius="2"/>', 'sphere'),
        (b'<Cylinder height="2" radius="1"/>', 'cylinder'),
        (b'<Cone height="2" bottomRadius="1"/>', 'cylinder'),
        (b'<IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0"/>'
         b'</IndexedFaceSet>', 'trimesh'),
        (b'<TriangleSet><Coordinate point="0 0 0 1 0 0 0 1 0"/></TriangleSet>', 'trimesh'),
    ])
    def test_each_geometry_has_a_shape(self, geometry, kind):
        graph = scene(b'<CollidableShape DEF="G"><Shape containerField="shape">' + geometry
                      + b'</Shape></CollidableShape>')
        found = x3drigid.geometry_shape(graph.getDEF('G').shape.geometry, moving=False)
        assert found.type == kind

    def test_a_moving_mesh_is_its_hull(self):
        graph = scene(b'''<CollidableShape DEF="G"><Shape containerField="shape">
          <TriangleSet><Coordinate point="0 0 0 1 0 0 0 1 0"/></TriangleSet>
          </Shape></CollidableShape>''')
        found = x3drigid.geometry_shape(graph.getDEF('G').shape.geometry, moving=True)
        assert found.type == 'convex'

    def test_a_cone_narrows_to_its_tip(self):
        graph = scene(b'''<CollidableShape DEF="G"><Shape containerField="shape">
          <Cone height="2" bottomRadius="1"/></Shape></CollidableShape>''')
        found = x3drigid.geometry_shape(graph.getDEF('G').shape.geometry, moving=True)
        assert (found.radiusBottom, found.radiusTop, found.height) == (1.0, 0.0, 2.0)

    def test_a_collidable_offset_moves_its_shape_in_the_body(self):
        graph = scene(b'''<CollidableOffset DEF="O" translation="5 5 5">
          <CollidableShape DEF="G" containerField="collidable" translation="0 1 0">
            <Shape containerField="shape"><Box size="1 1 1"/></Shape></CollidableShape>
          </CollidableOffset>''')
        parts = x3drigid.collidable_parts(graph.getDEF('O'), moving=True)
        assert len(parts) == 1
        assert np.allclose(parts[0].position, (0, 1, 0))


class TestJoints:
    HINGE = b'''<CollidableShape DEF="BAR"><Shape containerField="shape">
        <Box size="1 0.1 0.1"/></Shape></CollidableShape>
      <RigidBodyCollection DEF="C">
        <RigidBody DEF="B" containerField="bodies" position="0.5 0 0">
          <CollidableShape USE="BAR" containerField="geometry"/></RigidBody>
        <SingleAxisHingeJoint DEF="J" containerField="joints" anchorPoint="0 0 0" axis="0 0 1"
          %s><RigidBody USE="B" containerField="body2"/></SingleAxisHingeJoint>
      </RigidBodyCollection>'''

    def test_a_hinge_to_the_world_swings(self):
        graph = scene(self.HINGE % b'forceOutput="ALL"')
        run(graph.getDEF('C'), 0.4)
        joint, body = graph.getDEF('J'), graph.getDEF('B')
        assert joint.angle < -0.5
        assert joint.angleRate < 0.0
        assert np.allclose(joint.body2AnchorPoint, (0, 0, 0), atol=0.02)
        assert abs(body.position[2]) < 0.01

    def test_no_outputs_unless_asked(self):
        graph = scene(self.HINGE % b'')
        run(graph.getDEF('C'), 0.4)
        assert 'angle' not in graph.getDEF('J').__dict__

    def test_only_the_outputs_named(self):
        graph = scene(self.HINGE % b'forceOutput=\'"angleRate"\'')
        run(graph.getDEF('C'), 0.4)
        assert 'angleRate' in graph.getDEF('J').__dict__
        assert 'angle' not in graph.getDEF('J').__dict__

    def test_hinge_stops(self):
        graph = scene(self.HINGE % b'forceOutput="ALL" minAngle="-0.3" maxAngle="0.3"')
        run(graph.getDEF('C'), 1.5)
        assert graph.getDEF('J').angle == pytest.approx(-0.3, abs=0.03)

    def test_a_ball_joint_between_bodies(self):
        graph = scene(b'''<RigidBodyCollection DEF="C">
          <RigidBody DEF="A" containerField="bodies" fixed="true"/>
          <RigidBody DEF="B" containerField="bodies" position="1 0 0"/>
          <BallJoint DEF="J" containerField="joints" anchorPoint="0 0 0" forceOutput="ALL">
            <RigidBody USE="A" containerField="body1"/><RigidBody USE="B" containerField="body2"/>
          </BallJoint></RigidBodyCollection>''')
        run(graph.getDEF('C'), 0.5)
        joint = graph.getDEF('J')
        assert np.allclose(joint.body1AnchorPoint, joint.body2AnchorPoint, atol=0.02)
        assert np.linalg.norm(graph.getDEF('B').position) == pytest.approx(1.0, abs=0.02)

    def test_a_slider_between_its_stops(self):
        graph = scene(b'''<RigidBodyCollection DEF="C">
          <RigidBody DEF="B" containerField="bodies"/>
          <SliderJoint DEF="J" containerField="joints" axis="0 1 0" minSeparation="-0.5"
            maxSeparation="0.5" forceOutput="ALL">
            <RigidBody USE="B" containerField="body2"/></SliderJoint></RigidBodyCollection>''')
        run(graph.getDEF('C'), 1.5)
        assert graph.getDEF('J').separation == pytest.approx(-0.5, abs=0.03)

    def test_a_double_axis_hinge_drives_its_wheel(self):
        graph = scene(b'''<RigidBodyCollection DEF="C">
          <RigidBody DEF="CAR" containerField="bodies" fixed="true"/>
          <RigidBody DEF="WHEEL" containerField="bodies" position="1 0 0"
            useGlobalGravity="false"><Sphere containerField="massDensityModel" radius="0.3"/>
          </RigidBody>
          <DoubleAxisHingeJoint DEF="J" containerField="joints" anchorPoint="1 0 0"
            axis1="0 1 0" axis2="1 0 0" minAngle1="0" maxAngle1="0"
            desiredAngularVelocity2="4" maxTorque2="10" forceOutput="ALL">
            <RigidBody USE="CAR" containerField="body1"/>
            <RigidBody USE="WHEEL" containerField="body2"/></DoubleAxisHingeJoint>
          </RigidBodyCollection>''')
        run(graph.getDEF('C'), 1.0)
        joint = graph.getDEF('J')
        assert joint.hinge2AngleRate == pytest.approx(4.0, abs=0.05)
        assert joint.hinge1Angle == pytest.approx(0.0, abs=0.01)
        assert np.allclose(joint.body2Axis, (1, 0, 0), atol=0.01)

    def test_a_universal_joint_keeps_its_axes_square(self):
        graph = scene(b'''<RigidBodyCollection DEF="C">
          <RigidBody DEF="A" containerField="bodies" position="-0.5 0 0" angularVelocity="3 0 0"
            useGlobalGravity="false"/>
          <RigidBody DEF="B" containerField="bodies" position="0.5 0 0"
            useGlobalGravity="false"/>
          <UniversalJoint DEF="J" containerField="joints" axis1="0 1 0" axis2="0 0 1"
            forceOutput="ALL">
            <RigidBody USE="A" containerField="body1"/><RigidBody USE="B" containerField="body2"/>
          </UniversalJoint></RigidBodyCollection>''')
        run(graph.getDEF('C'), 1.0)
        joint = graph.getDEF('J')
        assert abs(float(np.dot(joint.body1Axis, joint.body2Axis))) < 0.02
        assert graph.getDEF('B').angularVelocity[0] > 1.0

    def test_a_motor_joint_turns_its_bodies(self):
        graph = scene(b'''<RigidBodyCollection DEF="C">
          <RigidBody DEF="A" containerField="bodies" fixed="true"/>
          <RigidBody DEF="B" containerField="bodies" useGlobalGravity="false" inertia="1 0 0 0 1 0 0 0 1"/>
          <MotorJoint DEF="J" containerField="joints" enabledAxes="1" motor1Axis="0 1 0"
            axis1Torque="0.5" autoCalc="true" forceOutput="ALL">
            <RigidBody USE="A" containerField="body1"/><RigidBody USE="B" containerField="body2"/>
          </MotorJoint></RigidBodyCollection>''')
        run(graph.getDEF('C'), 1.0)
        joint = graph.getDEF('J')
        assert joint.motor1AngleRate == pytest.approx(0.5, abs=0.02)
        assert joint.motor1Angle == pytest.approx(0.25, abs=0.02)


def test_the_parameters_a_collection_applies():
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    collection = x3d.CollisionCollection(
        appliedParameters=['BOUNCE', 'FRICTION_COEFFICIENT-2', 'SPEED-1', 'SLIP-2',
                           'ERROR_REDUCTION', 'CONSTANT_FORCE'],
        bounce=0.7, minBounceSpeed=0.3, frictionCoefficients=(0.5, 0.25),
        surfaceSpeed=(2.0, 3.0), slipFactors=(0.1, 0.2), softnessErrorCorrection=0.4,
        softnessConstantForceMix=0.01)
    found = x3drigid.contact_parameters(collection)
    assert (found.restitution, found.bounce_speed) == (pytest.approx(0.7), pytest.approx(0.3))
    assert found.frictions == (pytest.approx(0.5), pytest.approx(0.25))
    assert found.surface_speed == (pytest.approx(2.0), 0.0)
    assert found.slip == (0.0, pytest.approx(0.2))
    assert found.error_correction == pytest.approx(0.4)
    assert found.softness == pytest.approx(0.01)
    plain = x3drigid.contact_parameters(x3d.CollisionCollection(frictionCoefficients=(0.5, 0.25)))
    assert plain.restitution == 0.0
    assert plain.frictions == (pytest.approx(0.5), pytest.approx(0.5))
    assert plain.error_correction is None and plain.softness is None


class QueueContext:
    """A context's render queue and redraw requests, with no window"""

    def __init__(self):
        from OpenGLContext.events.renderqueue import RenderQueue  # noqa: PLC0415 kept with its use
        self.renderQueue = RenderQueue()
        self.redraws = 0

    def triggerRedraw(self, force=0):
        self.redraws += 1


def test_a_collection_steps_through_its_contexts_queue_on_the_engines_clock(monkeypatch):
    from OpenGLContext.events import systemtime  # noqa: PLC0415 kept with its use
    now = [100.0]
    monkeypatch.setattr(systemtime, 'systemTime', lambda: now[0])
    graph = falling()
    collection, body = graph.getDEF('C'), graph.getDEF('B')
    context = QueueContext()
    collection.bind(context)
    collection.bind(context)
    context.renderQueue.run()
    assert np.allclose(graph.getDEF('BALL-GEOM').translation, (0, 2, 0))
    for _ in range(30):
        now[0] += FRAME
        context.renderQueue.run()
    assert body.position[1] == pytest.approx(2.0 - 0.5 * 9.8 * 0.25, abs=0.05)
    assert context.redraws >= 30


def test_a_sensor_senses_each_frame():
    graph = scene(BALL + b'''<CollisionSensor DEF="S"><CollisionCollection containerField="collider">
        <CollidableShape USE="BALL-GEOM"/><CollidableShape USE="GROUND-GEOM"/>
        </CollisionCollection></CollisionSensor>''')
    sensor = graph.getDEF('S')
    context = QueueContext()
    sensor.bind(context)
    graph.getDEF('BALL-GEOM').translation = (0, -0.4, 0)
    context.renderQueue.run()
    assert sensor.isActive is True
    graph.getDEF('BALL-GEOM').translation = (0, 1, 0)
    context.renderQueue.run()
    assert sensor.isActive is False


def test_a_document_draws_its_bodies_where_they_are(gl_context):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    graph = scene(b'''<Background skyColor="0 0 0"/><Viewpoint position="0 0 6"/>
      <CollidableShape DEF="G"><Shape containerField="shape">
        <Appearance><UnlitMaterial emissiveColor="1 1 1"/></Appearance><Box size="1 1 1"/>
      </Shape></CollidableShape>
      <RigidBodyCollection><RigidBody containerField="bodies" position="1.5 0 0" fixed="true">
        <CollidableShape USE="G" containerField="geometry"/></RigidBody>
      </RigidBodyCollection>''')
    with scene_context(graph, size=(64, 64)) as context:
        drawn_image(context)
        context.renderQueue.run()
        image = drawn_image(context)
    assert image[32, 32].max() < 64
    assert image[32, 48].max() > 128


def _shape_facts(shape):
    if shape is None:
        return None
    return (shape.type, tuple(shape.size), shape.radius, shape.height, shape.radiusBottom,
            shape.radiusTop, None if shape.points is None else shape.points.tobytes(),
            None if shape.indices is None else shape.indices.tobytes())


@pytest.mark.parametrize('geometry, edits', [
    (b'<Box size="1 2 3"/>', [('size', lambda node: setattr(node, 'size', (2, 2, 2)))]),
    (b'<Sphere radius="2"/>', [('radius', lambda node: setattr(node, 'radius', 3.0))]),
    (b'<Cylinder height="2" radius="1"/>', [
        ('height', lambda node: setattr(node, 'height', 3.0)),
        ('radius', lambda node: setattr(node, 'radius', 0.5))]),
    (b'<Cone height="2" bottomRadius="1"/>', [
        ('height', lambda node: setattr(node, 'height', 3.0)),
        ('bottomRadius', lambda node: setattr(node, 'bottomRadius', 0.5))]),
    (b'<IndexedFaceSet coordIndex="0 1 2 -1"><Coordinate point="0 0 0 1 0 0 0 1 0 0 0 1"/>'
     b'</IndexedFaceSet>', [
        ('coord.point', lambda node: setattr(node.coord, 'point', [
            (0, 0, 0), (2, 0, 0), (0, 2, 0), (0, 0, 1)])),
        ('coordIndex', lambda node: setattr(node, 'coordIndex', [0, 1, 3, -1]))]),
])
@pytest.mark.parametrize('moving', [False, True])
def test_a_geometrys_shape_follows_its_fields(geometry, edits, moving, check_memo_inputs):
    graph = scene(b'<CollidableShape DEF="G"><Shape containerField="shape">' + geometry
                  + b'</Shape></CollidableShape>')
    node = graph.getDEF('G').shape.geometry
    check_memo_inputs(
        lambda: _shape_facts(x3drigid.geometry_shape(node, moving)),
        [(name, lambda edit=edit: edit(node)) for name, edit in edits],
        fresh=lambda: _shape_facts(x3drigid.shape_of_geometry(node, moving)))


def _world_facts(system):
    world = system.world
    count = world.body_count
    return (count, tuple(np.round(world.mass[:count], 6)),
            tuple(np.round(world.inv_inertia[:count].ravel(), 6)),
            tuple(np.round(world.position[:count].ravel(), 6)),
            tuple(np.round((world.aabb_max - world.aabb_min)[:count].ravel(), 6)),
            tuple(world.motion_type[:count]), len(world.row_joints),
            tuple(sorted(str(shape.type) for shape in world.shapes)))


def test_a_collections_world_follows_what_it_is_built_from(check_memo_inputs):
    graph = scene(BALL + b'''<CollidableShape DEF="OTHER"><Shape containerField="shape">
        <Box size="0.2 0.2 0.2"/></Shape></CollidableShape>
      <RigidBodyCollection DEF="C">
        <CollisionCollection DEF="CC" containerField="collider">
          <CollidableShape USE="BALL-GEOM"/></CollisionCollection>
        <RigidBody DEF="B" containerField="bodies" position="0 2 0">
          <CollidableShape USE="BALL-GEOM" containerField="geometry"/></RigidBody>
        <RigidBody DEF="B2" containerField="bodies" position="1 2 0"/>
      </RigidBodyCollection>''')
    collection, body = graph.getDEF('C'), graph.getDEF('B')

    def ask():
        collection.advance(0.0)
        return _world_facts(collection.system)

    def fresh():
        system = x3drigid.RigidSystem(collection)
        system.advance(0.0)
        return _world_facts(system)

    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept with its use
    check_memo_inputs(ask, [
        ('mass', lambda: setattr(body, 'mass', 3.0)),
        ('centerOfMass', lambda: setattr(body, 'centerOfMass', (0.0, 0.5, 0.0))),
        ('massDensityModel', lambda: setattr(body, 'massDensityModel', x3d.Box())),
        ('inertia', lambda: setattr(body, 'inertia', (5, 0, 0, 0, 5, 0, 0, 0, 5))),
        ('geometry', lambda: setattr(body, 'geometry', [graph.getDEF('OTHER')])),
        ('the geometry\'s size', lambda: setattr(
            graph.getDEF('OTHER').shape.geometry, 'size', (1, 1, 1))),
        ('enabled', lambda: setattr(graph.getDEF('B2'), 'enabled', False)),
        ('joints', lambda: setattr(collection, 'joints', [x3d.BallJoint(body1=body)])),
        ('collider', lambda: setattr(graph.getDEF('CC'), 'collidables',
                                     [graph.getDEF('GROUND-GEOM')])),
        ('fixed', lambda: setattr(body, 'fixed', True)),
        ('bodies', lambda: setattr(collection, 'bodies', [])),
    ], fresh=fresh)


@pytest.mark.serial
def test_a_frame_costs_what_the_collection_holds(check_scaling):
    """A frame's work, read in, stepped and sent, grows with the bodies and no faster"""
    def prepare(count):
        bodies = b''.join(b'''<RigidBody containerField="bodies" position="%d 0 0"
            useGlobalGravity="false" linearVelocity="0 1 0">
            <Sphere containerField="massDensityModel"/></RigidBody>''' % index
                          for index in range(count))
        graph = scene(b'<RigidBodyCollection DEF="C">' + bodies + b'</RigidBodyCollection>')
        collection = graph.getDEF('C')
        collection.advance(FRAME)
        return lambda: collection.advance(FRAME)

    check_scaling(prepare, n=50, most=6.0)


def test_a_bodys_settings_follow_its_fields(check_memo_inputs):
    graph = falling()
    collection, body = graph.getDEF('C'), graph.getDEF('B')

    def facts(system):
        world, index = system.world, system.bodies[0].index
        return (tuple(world.force[index]), tuple(world.torque[index]),
                float(world.gravity_factor[index]), float(world.linear_damping[index]),
                float(world.angular_damping[index]),
                bool(world._exact_rotation[index]),  # noqa: SLF001 the flag set_exact_rotation sets
                float(world._sleep_linear[index]),  # noqa: SLF001 the thresholds set_sleep sets
                float(world._sleep_angular[index]),  # noqa: SLF001 the thresholds set_sleep sets
                float(world._sleep_after[index]))  # noqa: SLF001 the thresholds set_sleep sets

    def ask():
        collection.advance(0.0)
        return facts(collection.system)

    def fresh():
        system = x3drigid.RigidSystem(collection)
        system.advance(0.0)
        return facts(system)

    check_memo_inputs(ask, [
        ('forces', lambda: setattr(body, 'forces', [(1, 0, 0)])),
        ('torques', lambda: setattr(body, 'torques', [(0, 1, 0)])),
        ('useGlobalGravity', lambda: setattr(body, 'useGlobalGravity', False)),
        ('autoDamp', lambda: setattr(body, 'autoDamp', True)),
        ('linearDampingFactor', lambda: setattr(body, 'linearDampingFactor', 0.1)),
        ('angularDampingFactor', lambda: setattr(body, 'angularDampingFactor', 0.2)),
        ('useFiniteRotation', lambda: setattr(body, 'useFiniteRotation', True)),
        ('the collection\'s autoDisable', lambda: setattr(collection, 'autoDisable', True)),
        ('the collection\'s disableTime', lambda: setattr(collection, 'disableTime', 2.0)),
        ('autoDisable', lambda: setattr(body, 'autoDisable', True)),
        ('disableLinearSpeed', lambda: setattr(body, 'disableLinearSpeed', 0.3)),
        ('disableAngularSpeed', lambda: setattr(body, 'disableAngularSpeed', 0.4)),
        ('disableTime', lambda: setattr(body, 'disableTime', 1.5)),
    ], fresh=fresh)
