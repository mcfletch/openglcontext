"""X3D's HAnim nodes in the engine: a humanoid drawn, skinned, posed and animated.

The humanoid here is an arm: a box from the root out to x = 2, its near four
points moved by `humanoid_root` and its far four by `l_shoulder`, which turns
about (0, 1, 0). A quarter turn about Z stands the arm up to y = 3.
"""
import math

import numpy as np
import pytest

from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph import coordinatedeform, hanim

SKIN_POINTS = ('0 0.9 -0.1, 0 1.1 -0.1, 0 1.1 0.1, 0 0.9 0.1, '
               '2 0.9 -0.1, 2 1.1 -0.1, 2 1.1 0.1, 2 0.9 0.1')
FACES = '0 4 5 1 -1 1 5 6 2 -1 2 6 7 3 -1 3 7 4 0 -1 0 1 2 3 -1 4 7 6 5 -1'


def arm(humanoid='', shoulder='', extra='', root_weights='1 1 1 1', scene=''):
    """The arm document, with attributes and children added where named"""
    return ('''<X3D version="4.0"><Scene>
      <Background skyColor="0 0 0"/><Viewpoint position="1 1.5 9"/>
      <HAnimHumanoid DEF="H" name="arm" version="2.0" %s>
        <HAnimJoint DEF="ROOT" containerField="skeleton" name="humanoid_root"
            skinCoordIndex="0 1 2 3" skinCoordWeight="%s">
          <HAnimJoint DEF="SHOULDER" name="l_shoulder" center="0 1 0"
              skinCoordIndex="4 5 6 7" skinCoordWeight="1 1 1 1" %s>
            <HAnimSegment DEF="UPPER" name="l_upperarm"/>
            <HAnimSite DEF="TIP" name="l_radial_styloid" translation="2 1 0"/>
          </HAnimJoint>
        </HAnimJoint>
        <HAnimJoint USE="ROOT" containerField="joints"/>
        <HAnimJoint USE="SHOULDER" containerField="joints"/>
        <Coordinate DEF="SKIN" containerField="skinCoord" point="%s"/>
        <Shape DEF="ARM" containerField="skin">
          <Appearance><UnlitMaterial emissiveColor="1 1 1"/></Appearance>
          <IndexedFaceSet DEF="MESH" solid="false" coordIndex="%s"><Coordinate USE="SKIN"/></IndexedFaceSet>
        </Shape>
        %s
      </HAnimHumanoid>
      %s
    </Scene></X3D>''' % (humanoid, root_weights, shoulder, SKIN_POINTS, FACES, extra, scene)).encode()


def load(document):
    return Loader.loads(document, 'arm.x3d')


def posed(scene):
    """The arm's vertices where the pose puts them"""
    geometry = scene.getDEF('MESH')
    mesh = coordinatedeform.deformer_for(geometry).mesh(geometry)
    return mesh.posed_positions()


def top(volume):
    return float(np.asarray(volume.getPoints())[:, 1].max())


def quarter_turn(scene):
    scene.getDEF('SHOULDER').rotation = (0, 0, 1, math.pi / 2)


class TestTheHumanoid:
    def test_it_draws_its_skeleton_and_skin(self):
        scene = load(arm())
        humanoid = scene.getDEF('H')
        assert humanoid.renderedChildren() == [scene.getDEF('ROOT'), scene.getDEF('ARM')]

    def test_a_viewpoint_site_the_skeleton_places_is_drawn_there(self):
        scene = load(arm(extra='<HAnimSite USE="TIP" containerField="viewpoints"/>'
                               '<HAnimSite DEF="VIEW" containerField="viewpoints"/>'))
        found = scene.getDEF('H').renderedChildren()
        assert scene.getDEF('VIEW') in found and scene.getDEF('TIP') not in found

    def test_a_joint_draws_its_joints_segments_and_sites(self):
        scene = load(arm().replace(b'<HAnimSegment DEF="UPPER"',
                                   b'<Transform DEF="MARKER"/><HAnimSegment DEF="UPPER"'))
        shoulder = scene.getDEF('SHOULDER')
        assert scene.getDEF('MARKER') in shoulder.children
        assert shoulder.renderedChildren() == [scene.getDEF('UPPER'), scene.getDEF('TIP')]

    def test_its_joints_are_found_by_name_and_alias(self):
        scene = load(arm())
        humanoid = scene.getDEF('H')
        assert humanoid.joint('l_shoulder') is scene.getDEF('SHOULDER')
        assert humanoid.joint('HumanoidRoot') is scene.getDEF('ROOT')

    def test_its_transform_places_it(self):
        scene = load(arm(humanoid='translation="0 5 0"'))
        assert 6.1 - 1e-4 <= top(scene.getDEF('H').boundingVolume(None)) <= 6.15


class TestTheSkin:
    def test_the_skin_geometry_is_drawn_through_the_humanoid(self):
        scene = load(arm())
        scene.getDEF('H').rig()
        assert isinstance(coordinatedeform.deformer_for(scene.getDEF('MESH')),
                          hanim.SkinDeformer)

    def test_at_rest_the_skin_is_where_its_points_are(self):
        scene = load(arm())
        scene.getDEF('H').rig()
        assert posed(scene)[:, 0].max() == pytest.approx(2.0, abs=1e-5)
        assert posed(scene)[:, 1].max() == pytest.approx(1.1, abs=1e-5)

    def test_a_turned_joint_carries_its_vertices(self):
        scene = load(arm())
        scene.getDEF('H').rig()
        quarter_turn(scene)
        points = posed(scene)
        assert points[:, 1].max() == pytest.approx(3.0, abs=1e-4)
        assert points[:, 0].max() == pytest.approx(0.1, abs=1e-4)

    def test_the_bounds_follow_the_pose(self):
        scene = load(arm())
        humanoid, shape = scene.getDEF('H'), scene.getDEF('ARM')
        humanoid.rig()
        # Joint spheres bound the skin: the arm's 0.2 square is reached by
        # a sphere of radius 0.1 * sqrt(2).
        assert 1.1 - 1e-4 <= top(shape.boundingVolume(None)) <= 1.15
        assert 1.1 - 1e-4 <= top(humanoid.boundingVolume(None)) <= 1.15
        quarter_turn(scene)
        assert top(shape.boundingVolume(None)) >= 3.0 - 1e-4
        assert top(humanoid.boundingVolume(None)) >= 3.0 - 1e-4

    def test_weights_short_of_one_leave_the_rest_where_it_was(self):
        """X3D's sum: v + w (M v - v), so half a weight moves half the way."""
        scene = load(arm(root_weights='1 1 1 1').replace(
            b'skinCoordIndex="4 5 6 7" skinCoordWeight="1 1 1 1"',
            b'skinCoordIndex="4 5 6 7" skinCoordWeight="0.5 0.5 0.5 0.5"'))
        scene.getDEF('H').rig()
        scene.getDEF('SHOULDER').translation = (0, 2, 0)
        assert posed(scene)[:, 1].max() == pytest.approx(2.1, abs=1e-4)

    def test_a_binding_matrix_is_applied_before_the_joint(self):
        scene = load(arm(humanoid='jointBindingPositions="0 0 0 0 0 1"'))
        scene.getDEF('H').rig()
        assert posed(scene)[:, 2].max() == pytest.approx(1.1, abs=1e-5)

    def test_binding_coordinates_are_the_rest_pose(self):
        binding = SKIN_POINTS.replace('2 ', '3 ')
        scene = load(arm(extra='<Coordinate containerField="skinBindingCoords" point="%s"/>'
                         % binding))
        scene.getDEF('H').rig()
        assert posed(scene)[:, 0].max() == pytest.approx(3.0, abs=1e-5)

    def test_a_joint_displacer_moves_its_points_by_its_weight(self):
        scene = load(arm(shoulder='', extra='').replace(
            b'<HAnimSegment DEF="UPPER"',
            b'<HAnimDisplacer DEF="D" containerField="displacers" coordIndex="6" '
            b'displacements="0 1 0" weight="0.5"/><HAnimSegment DEF="UPPER"'))
        scene.getDEF('H').rig()
        assert posed(scene)[:, 1].max() == pytest.approx(1.6, abs=1e-5)
        scene.getDEF('D').weight = 1.0
        assert posed(scene)[:, 1].max() == pytest.approx(2.1, abs=1e-5)

    def test_the_skin_follows_an_edit_of_a_joints_weights(self, check_memo_inputs):
        scene = load(arm())
        humanoid = scene.getDEF('H')
        humanoid.rig()
        quarter_turn(scene)
        shoulder = scene.getDEF('SHOULDER')
        geometry = scene.getDEF('MESH')

        def answer():
            return np.round(posed(scene), 4)

        check_memo_inputs(answer, [
            ('skinCoordWeight', lambda: setattr(shoulder, 'skinCoordWeight', [0.5] * 4)),
            ('skinCoordIndex', lambda: setattr(shoulder, 'skinCoordIndex', [4, 5])),
            ('skinCoord point', lambda: setattr(
                scene.getDEF('SKIN'), 'point',
                np.asarray(scene.getDEF('SKIN').point) * 2)),
            ('coordIndex', lambda: setattr(geometry, 'coordIndex', [0, 4, 5, 1, -1])),
            ('rotation', lambda: setattr(shoulder, 'rotation', (0, 0, 1, 1.0))),
            ('center', lambda: setattr(shoulder, 'center', (0, 0, 0))),
        ], same=lambda a, b: a.shape == b.shape and np.allclose(a, b))

    def test_a_deformed_shape_is_drawn_alone(self):
        from OpenGLContext.passes import instancing  # noqa: PLC0415 kept with its use
        scene = load(arm())
        scene.getDEF('H').rig()
        shape = scene.getDEF('ARM')
        assert instancing.geometry_instance_key(shape) is None
        assert instancing.geometry_content_key(shape) is None


class TestSegments:
    DOCUMENT = '''<X3D version="4.0"><Scene><HAnimHumanoid DEF="H">
      <HAnimJoint containerField="skeleton" name="humanoid_root">
        <HAnimSegment DEF="SEG" name="pelvis">
          <Coordinate DEF="C" containerField="coord" point="0 0 0, 1 0 0, 0 1 0"/>
          <HAnimDisplacer DEF="D" containerField="displacers" coordIndex="2"
              displacements="0 0 2" weight="0.25"/>
          <Shape><IndexedFaceSet DEF="G" coordIndex="0 1 2 -1"><Coordinate USE="C"/></IndexedFaceSet></Shape>
        </HAnimSegment>
      </HAnimJoint></HAnimHumanoid></Scene></X3D>'''

    def test_a_segment_displacer_moves_its_coordinates(self):
        scene = load(self.DOCUMENT.encode())
        geometry = scene.getDEF('G')
        deformer = coordinatedeform.deformer_for(geometry)
        assert isinstance(deformer, hanim.SegmentDeformer)
        assert deformer.mesh(geometry).positions[:, 2].max() == pytest.approx(0.5)
        scene.getDEF('D').weight = 0.5
        assert deformer.mesh(geometry).positions[:, 2].max() == pytest.approx(1.0)
        assert float(np.asarray(geometry.boundingVolume(None).getPoints())[:, 2].max()) \
            == pytest.approx(1.0)

    def test_a_segment_without_displacers_deforms_nothing(self):
        scene = load(self.DOCUMENT.encode())
        scene.getDEF('SEG').displacers = []
        assert coordinatedeform.deformer_for(scene.getDEF('G')) is None


class TestRoutes:
    def test_an_interpolator_routed_to_a_joint_poses_the_skin(self):
        scene = load(arm(scene='''
          <OrientationInterpolator DEF="TURN" key="0 1" keyValue="0 0 1 0, 0 0 1 1.5708"/>
          <ROUTE fromNode="TURN" fromField="value_changed" toNode="SHOULDER" toField="set_rotation"/>'''))
        scene.getDEF('H').rig()
        scene.getDEF('TURN').set_fraction = 1.0
        assert posed(scene)[:, 1].max() == pytest.approx(3.0, abs=1e-3)


MOTION = ('<HAnimMotion DEF="M" containerField="motions" joints="HumanoidRoot l_shoulder" '
          'channels="3 Xposition Yposition Zposition 1 Zrotation" frameDuration="0.5" %s '
          'values="0 0 0 0  0 0 0 90  0 0 0 0"/>')


class TestMotion:
    def make(self, attributes='loop="true"'):
        scene = load(arm(extra=MOTION % attributes))
        scene.getDEF('H').rig()
        return scene, scene.getDEF('M'), scene.getDEF('SHOULDER')

    def test_it_counts_its_frames(self):
        _scene, motion, _shoulder = self.make()
        assert motion.channelData().frames == 3
        assert motion.frameCount == 3

    def test_its_channels_drive_the_joints_as_time_passes(self):
        _scene, motion, shoulder = self.make()
        motion.advance(100.0)
        motion.advance(100.5)
        assert shoulder.rotation[3] == pytest.approx(math.pi / 2, abs=1e-5)
        assert motion.frameIndex == 1
        motion.advance(100.75)
        assert shoulder.rotation[3] == pytest.approx(math.pi / 4, abs=1e-5)

    def test_a_loop_starts_again(self):
        _scene, motion, shoulder = self.make()
        motion.advance(100.0)
        motion.advance(101.25)
        assert motion.frameIndex == 0
        assert shoulder.rotation[3] == pytest.approx(math.pi / 4, abs=1e-5)
        assert motion.cycleTime == pytest.approx(101.25)

    def test_without_a_loop_it_stops_at_the_end(self):
        _scene, motion, _shoulder = self.make('loop="false"')
        motion.advance(100.0)
        assert motion.advance(105.0) == 1
        assert motion.frameIndex == 2
        assert motion.advance(106.0) == 0
        assert motion.elapsedTime == pytest.approx(5.0)

    def test_next_and_previous_step_by_the_increment(self):
        _scene, motion, shoulder = self.make('loop="false" frameIncrement="0"')
        motion.advance(100.0)
        motion.next = True
        assert motion.frameIndex == 1
        assert shoulder.rotation[3] == pytest.approx(math.pi / 2, abs=1e-5)
        motion.previous = True
        assert motion.frameIndex == 0

    def test_a_disabled_channel_drives_nothing(self):
        _scene, motion, shoulder = self.make('loop="true" channelsEnabled="true false"')
        motion.advance(100.0)
        motion.advance(100.5)
        assert shoulder.rotation[3] == 0

    def test_a_motion_the_humanoid_has_not_enabled_drives_nothing(self):
        scene = load(arm(humanoid='motionsEnabled="false"', extra=MOTION % ''))
        scene.getDEF('H').rig()
        assert scene.getDEF('M').advance(100.0) == 0

    def test_disabled_it_stops(self):
        _scene, motion, _shoulder = self.make()
        motion.advance(100.0)
        motion.enabled = False
        assert motion.advance(100.5) == 0


POSE = ('<HAnimPose DEF="P" transitionDuration="%s">'
        '<HAnimJoint name="l_shoulder" rotation="0 0 1 1.5708"/></HAnimPose>')


class TestPose:
    def make(self, duration='0'):
        scene = load(arm(extra=POSE % duration))
        scene.getDEF('H').rig()
        return scene.getDEF('P'), scene.getDEF('SHOULDER')

    def test_commencing_a_pose_with_no_transition_sets_the_joints(self):
        pose, shoulder = self.make()
        pose.commencePose = True
        assert shoulder.rotation[3] == pytest.approx(1.5708, abs=1e-5)

    def test_a_transition_moves_the_joints_over_its_duration(self):
        pose, shoulder = self.make('2')
        pose.commencePose = True
        assert pose.isActive
        started = pose.__dict__['_started']
        pose.advance(started + 1.0)
        assert shoulder.rotation[3] == pytest.approx(0.7854, abs=1e-4)
        pose.advance(started + 2.0)
        assert shoulder.rotation[3] == pytest.approx(1.5708, abs=1e-4)
        assert not pose.isActive
        assert pose.advance(started + 3.0) == 0

    def test_a_fraction_sets_how_far_along_the_joints_are(self):
        pose, shoulder = self.make('2')
        pose.set_fraction = 0.5
        assert shoulder.rotation[3] == pytest.approx(0.7854, abs=1e-4)

    def test_resetting_puts_every_joint_back(self):
        pose, shoulder = self.make()
        shoulder.translation = (0, 3, 0)
        pose.resetAllJoints = True
        assert tuple(shoulder.translation) == (0, 0, 0)

    def test_a_disabled_pose_moves_nothing(self):
        pose, shoulder = self.make()
        pose.enabled = False
        pose.commencePose = True
        assert shoulder.rotation[3] == 0


class TestLimits:
    def test_a_joint_holds_a_rotation_to_its_limits(self):
        scene = load(arm(shoulder='llimit="0 0 -0.5" ulimit="0 0 0.5"'))
        found = scene.getDEF('SHOULDER').limitedRotation((0, 0, 1, 1.2))
        assert found[3] == pytest.approx(0.5, abs=1e-6)


# -- drawn ------------------------------------------------------------------

def _extent(image):
    """The width and height of what is drawn, in pixels"""
    rows, columns = np.nonzero(image[..., :3].max(axis=2) > 128)
    assert len(rows), 'nothing was drawn'
    return columns.max() - columns.min() + 1, rows.max() - rows.min() + 1


@pytest.mark.parametrize('renderer, profile, gpu', [
    ('pbr', 'core', '1'), ('pbr', 'core', '0'), ('vrml97', 'core', '1'),
    ('vrml97', 'compatibility', '0'),
])
def test_the_skin_is_drawn_where_the_pose_puts_it(gl_context, renderer, profile, gpu):
    """Along the X axis at rest, and stood up the Y axis turned."""
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = load(arm())
    with scene_context(scene, size=(64, 64), renderer=renderer,
                       environment={'OPENGLCONTEXT_GPU_SKINNING': gpu,
                                    'OPENGLCONTEXT_PROFILE': profile}) as context:
        rest = drawn_image(context)
        quarter_turn(scene)
        turned = drawn_image(context)
    width, height = _extent(rest)
    assert width > 3 * height
    width, height = _extent(turned)
    assert height > 3 * width


def test_a_drawn_humanoid_plays_its_motion(gl_context):
    from OpenGLContext.testing.scenes import drawn_image, scene_context  # noqa: PLC0415 GL
    scene = load(arm(extra=MOTION % 'loop="true"'))
    with scene_context(scene, size=(32, 32)) as context:
        for _frame in range(4):
            drawn_image(context)
        assert scene.getDEF('M').elapsedTime > 0
    assert scene.getDEF('SHOULDER').rotation[3] > 0


def test_a_still_humanoid_does_no_gl_work(gl_context, check_still_frame):
    from OpenGLContext.testing.scenes import scene_context  # noqa: PLC0415 GL
    scene = load(arm().replace(b'<Background skyColor="0 0 0"/>', b''))
    with scene_context(scene, size=(48, 48)) as context:
        quarter_turn(scene)
        check_still_frame(lambda: context.OnDraw(force=1))
