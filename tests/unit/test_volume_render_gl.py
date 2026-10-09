"""X3D's volume data nodes drawn by the ray march, in a real context.

Volumes made in code sit at the origin in front of the default viewpoint
(0, 0, 10), against a black background, and the frame is read back. The
equations come from 19775-1 41.4; tests/unit/test_volume_styles.py holds the
plan each draw is made from.
"""
import numpy as np
import pytest
from vrml.x3d import nodes as x3d

from OpenGLContext.scenegraph import basenodes, texture3d, volumestyles
from OpenGLContext.scenegraph.volumedata import IsoSurfaceVolumeData, SegmentedVolumeData, VolumeData
from OpenGLContext.testing.glcontext import profile_unavailable
from OpenGLContext.testing.scenes import drawn_image, scene_context
from OpenGLContext.testing.stillframe import check_still_frame

SIZE = 64
PBR = {'OPENGLCONTEXT_RENDERER': 'pbr'}


@pytest.fixture
def core():
    refused = profile_unavailable('core')
    if refused:
        pytest.skip(refused)


def voxels(values):
    """A PixelTexture3D of ``values``, a ``(depth, height, width[, channels])`` uint8 array"""
    values = np.asarray(values, np.uint8)
    if values.ndim == 3:
        values = values[..., None]
    depth, height, width, channels = values.shape
    shifts = np.arange(channels - 1, -1, -1) * 8
    packed = (values.reshape(-1, channels).astype(np.int64) << shifts).sum(-1)
    return texture3d.PixelTexture3D(image=[channels, width, height, depth] + packed.tolist())


def uniform(value, size=8):
    return voxels(np.full((size, size, size), value, np.uint8))


def ball(size=24, inside=255, outside=0, radius=0.35):
    """A sphere of ``inside`` in ``outside``, its edge blurred over a voxel"""
    axis = (np.arange(size) + 0.5) / size - 0.5
    z, y, x = np.meshgrid(axis, axis, axis, indexing='ij')
    distance = np.sqrt(x * x + y * y + z * z)
    share = np.clip((radius - distance) * size + 0.5, 0.0, 1.0)
    return voxels(np.round(outside + (inside - outside) * share).astype(np.uint8))


def drawn(children, environment=PBR, background=(0, 0, 0), frames=3, **definition):
    scene = list(children) + [basenodes.Background(skyColor=[background])]
    with scene_context(scene, size=(SIZE, SIZE), environment=environment,
                       **definition) as context:
        for _ in range(frames):
            context.renderQueue.run()
            context.OnDraw(force=1)
        return drawn_image(context).astype(int)


def centre(image):
    return image[SIZE // 2 - 2:SIZE // 2 + 2, SIZE // 2 - 2:SIZE // 2 + 2].reshape(-1, 3).mean(0)


def at_box(node, z):
    return basenodes.Transform(translation=(0, 0, z), children=[node])


def opaque_box(colour, z, size=(2, 2, 0.2)):
    return at_box(basenodes.Shape(
        appearance=basenodes.Appearance(material=basenodes.Material(
            diffuseColor=colour, emissiveColor=colour)),
        geometry=basenodes.Box(size=size)), z)


@pytest.mark.usefixtures('core')
def test_an_opaque_volume_is_drawn_in_its_voxel_colour():
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(255))])
    assert centre(image) == pytest.approx((255, 255, 255), abs=2)
    assert image[2, 2].tolist() == [0, 0, 0], 'outside the box is the background'


@pytest.mark.usefixtures('core')
def test_the_default_style_takes_opacity_from_the_voxels_first_component():
    """Grey 64 is a quarter opaque a voxel; eight voxels deep is 90% of it"""
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(64))])
    opacity = 1.0 - (1.0 - 64 / 255.0) ** 8
    assert centre(image)[0] == pytest.approx(64 * opacity, abs=3)


@pytest.mark.usefixtures('core')
def test_opacity_is_for_a_voxels_thickness_whatever_the_box_size():
    small = drawn([VolumeData(dimensions=(2, 2, 2), voxels=uniform(64))])
    large = drawn([VolumeData(dimensions=(6, 6, 6), voxels=uniform(64))])
    assert centre(small)[0] == pytest.approx(centre(large)[0], abs=3)


@pytest.mark.usefixtures('core')
def test_the_first_slice_is_at_minus_z():
    """19775-1 41.2.2.1: the slices go along +Z, so r=0 is the far one seen from +Z"""
    values = np.zeros((8, 8, 8), np.uint8)
    values[0] = 255                    # the first slice: opaque white
    values[1:] = 40                    # the rest: dim grey, partly see-through
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=voxels(values))])
    # Seen through the dim slices, the white one shows behind them.
    seen = centre(image)[0]
    dim = 40 * (1.0 - (1.0 - 40 / 255.0) ** 7)
    assert seen > dim + 20


@pytest.mark.usefixtures('core')
def test_opaque_geometry_hides_the_volume_behind_it_and_is_hidden_by_the_volume_in_front():
    alone = centre(drawn([opaque_box((1, 0, 0), 3.0)]))
    front = centre(drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(40)),
                          opaque_box((1, 0, 0), 3.0)]))
    inside = centre(drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(40)),
                           opaque_box((1, 0, 0), 0.0)]))
    behind = centre(drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(40)),
                           opaque_box((1, 0, 0), -3.0)]))
    assert front == pytest.approx(alone, abs=2)
    # Inside, only the volume's front half is over the box.
    assert behind[0] < inside[0] < front[0]
    assert inside[1] < behind[1]


@pytest.mark.usefixtures('core')
def test_a_camera_inside_the_volume_sees_it():
    image = drawn([VolumeData(dimensions=(30, 30, 30), voxels=uniform(255))])
    assert centre(image)[0] > 250


@pytest.mark.usefixtures('core')
def test_a_volume_with_a_zero_dimension_is_a_plane():
    image = drawn([VolumeData(dimensions=(4, 4, 0), voxels=uniform(255))])
    assert centre(image)[0] > 250


@pytest.mark.usefixtures('core')
def test_an_isosurface_is_opaque_in_its_voxel_colour():
    """X_ITE draws surfaceValues 0.3 with no style as grey 76: 0.3 of 255"""
    node = IsoSurfaceVolumeData(dimensions=(6, 6, 6), voxels=ball(), surfaceValues=[0.3])
    assert centre(drawn([node])) == pytest.approx((76, 76, 76), abs=6)


@pytest.mark.usefixtures('core')
def test_no_surface_value_draws_no_surface():
    node = IsoSurfaceVolumeData(dimensions=(6, 6, 6), voxels=ball())
    assert centre(drawn([node])) == pytest.approx((0, 0, 0), abs=1)


@pytest.mark.usefixtures('core')
@pytest.mark.parametrize('kind, expected', [('MAX', 255), ('MIN', 0), ('AVERAGE', None)])
def test_projection_takes_the_rays_greatest_least_or_mean_value(kind, expected):
    node = VolumeData(dimensions=(6, 6, 6), voxels=ball(),
                      renderStyle=x3d.ProjectionVolumeStyle(type=kind))
    seen = centre(drawn([node]))[0]
    if expected is None:
        # A ray through the middle crosses the ball for 0.7 of the box.
        assert 255 * 0.55 < seen < 255 * 0.8
    else:
        assert seen == pytest.approx(expected, abs=6)


@pytest.mark.usefixtures('core')
def test_a_disabled_segment_is_not_drawn():
    left = np.zeros((8, 8, 8), np.uint8)
    left[:, :, 4:] = 1                         # segment 1 on the right
    node = SegmentedVolumeData(dimensions=(4, 4, 4), voxels=uniform(255),
                               segmentIdentifiers=voxels(left), segmentEnabled=[True, False])
    image = drawn([node])
    row = image[SIZE // 2]
    assert row[SIZE // 2 - 6:SIZE // 2 - 2, 0].min() > 250
    assert row[SIZE // 2 + 2:SIZE // 2 + 6, 0].max() < 5


@pytest.mark.usefixtures('core')
def test_tone_mapping_is_warm_where_the_surface_faces_the_headlight():
    node = VolumeData(dimensions=(6, 6, 6), voxels=ball(),
                      renderStyle=x3d.ToneMappedVolumeStyle())
    red, green, blue = centre(drawn([node]))
    assert red > 200 and green > 200 and blue < 60


@pytest.mark.usefixtures('core')
def test_the_shaded_style_unlit_is_its_materials_diffuse_colour():
    style = x3d.ShadedVolumeStyle(material=x3d.Material(diffuseColor=(0, 0.6, 1)))
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(255), renderStyle=style)])
    assert centre(image) == pytest.approx((0, 153, 255), abs=3)


@pytest.mark.usefixtures('core')
def test_the_shaded_style_lit_by_the_headlight_is_brightest_facing_it():
    style = x3d.ShadedVolumeStyle(lighting=True, material=x3d.Material(
        diffuseColor=(1, 1, 1), ambientIntensity=0.0))
    image = drawn([VolumeData(dimensions=(6, 6, 6), voxels=ball(), renderStyle=style)])
    middle = centre(image)[0]
    edge = image[SIZE // 2, SIZE // 2 + 12, 0]
    assert middle > 200 and edge < middle


@pytest.mark.usefixtures('core')
def test_a_transfer_function_gives_the_colour():
    table = x3d.PixelTexture(image=[2, 1, 4, 0x00000000, 0xFF8000FF])
    style = x3d.OpacityMapVolumeStyle(transferFunction=table)
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(255), renderStyle=style)])
    assert centre(image) == pytest.approx((255, 128, 0), abs=3)
    table.image = [2, 1, 4, 0x00000000, 0x0080FFFF]
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(255), renderStyle=style)])
    assert centre(image) == pytest.approx((0, 128, 255), abs=3)


@pytest.mark.usefixtures('core')
def test_a_blended_style_mixes_in_a_second_volume():
    style = x3d.BlendedVolumeStyle(
        voxels=uniform(255), weightConstant1=0.0, weightConstant2=1.0,
        renderStyle=x3d.ShadedVolumeStyle(material=x3d.Material(diffuseColor=(1, 0, 0))))
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(255), renderStyle=style)])
    assert centre(image) == pytest.approx((255, 0, 0), abs=3)


@pytest.mark.usefixtures('core')
def test_the_bloom_composite_shows_the_same_colour():
    plain = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(128))])
    bloomed = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(128))],
                    environment=dict(PBR, OPENGLCONTEXT_BLOOM='1'))
    assert centre(bloomed) == pytest.approx(centre(plain), abs=8)


@pytest.mark.usefixtures('core')
def test_the_vrml97_renderer_draws_volumes_too():
    image = drawn([VolumeData(dimensions=(4, 4, 4), voxels=uniform(255))],
                  environment={'OPENGLCONTEXT_RENDERER': 'flat'})
    assert centre(image) == pytest.approx((255, 255, 255), abs=2)


def test_the_compatibility_profile_draws_volumes_with_the_same_program():
    refused = profile_unavailable('compatibility')
    if refused:
        pytest.skip(refused)
    node = VolumeData(dimensions=(6, 6, 6), voxels=ball(),
                      renderStyle=x3d.ToneMappedVolumeStyle())
    red, green, blue = centre(drawn([node], environment={
        'OPENGLCONTEXT_PROFILE': 'compatibility'}))
    assert red > 200 and green > 200 and blue < 60


@pytest.mark.usefixtures('core')
def test_every_style_and_mode_links():
    """The GLSL each kind of plan generates compiles and links"""
    from OpenGLContext.passes.volumepass import VolumePrograms
    table2d = x3d.PixelTexture(image=[2, 1, 4, 0, 0xFFFFFFFF])
    normals = voxels(np.full((4, 4, 4, 3), 128, np.uint8))
    every = x3d.ComposedVolumeStyle(renderStyle=[
        x3d.OpacityMapVolumeStyle(transferFunction=table2d),
        x3d.OpacityMapVolumeStyle(transferFunction=voxels(np.zeros((2, 2, 2, 4), np.uint8))),
        x3d.BoundaryEnhancementVolumeStyle(), x3d.CartoonVolumeStyle(surfaceNormals=normals),
        x3d.EdgeEnhancementVolumeStyle(), x3d.SilhouetteEnhancementVolumeStyle(),
        x3d.ToneMappedVolumeStyle(), x3d.ShadedVolumeStyle(),
        x3d.ShadedVolumeStyle(lighting=True, material=x3d.Material()),
        x3d.BlendedVolumeStyle(voxels=ball(), weightFunction1='TABLE',
                               weightTransferFunction1=table2d, weightFunction2='ALPHA2',
                               renderStyle=x3d.CartoonVolumeStyle()),
    ])
    nodes = [
        VolumeData(voxels=uniform(9), renderStyle=every),
        VolumeData(voxels=uniform(9), renderStyle=x3d.ProjectionVolumeStyle()),
        SegmentedVolumeData(voxels=uniform(9), segmentIdentifiers=uniform(1),
                            renderStyle=[every, x3d.ToneMappedVolumeStyle()]),
        IsoSurfaceVolumeData(voxels=uniform(9), gradients=normals, surfaceValues=[0.2, 0.5],
                             renderStyle=[every, x3d.CartoonVolumeStyle()]),
    ]
    with scene_context([], size=(16, 16), environment=PBR) as context:
        context.OnDraw(force=1)
        programs = VolumePrograms()
        try:
            for node in nodes:
                assert programs.program(volumestyles.plan(node)) is not None, node
        finally:
            programs.release()


@pytest.mark.usefixtures('core')
def test_a_still_frame_compiles_and_makes_nothing():
    nodes = [VolumeData(dimensions=(4, 4, 4), voxels=ball(),
                        renderStyle=x3d.ToneMappedVolumeStyle())]
    with scene_context(nodes, size=(SIZE, SIZE), environment=PBR) as context:
        def frame():
            context.renderQueue.run()
            context.OnDraw(force=1)
        # The opaque depth is copied into its texture each frame that draws a volume.
        work = check_still_frame(frame, uploads=1)
    assert work.allocations == work.compiles == 0, work


def _pick(node):
    from OpenGLContext.events.mouseevents import MouseButtonEvent
    found = {}
    scene = [node, basenodes.Background(skyColor=[(0, 0, 0)])]
    with scene_context(scene, size=(SIZE, SIZE), environment=PBR) as context:
        context.contextDefinition.pickAsync = True

        def hit(event):
            paths = event.getObjectPaths()
            found['node'] = paths[0][-1] if paths and paths[0] else None
            found['point'] = event.viewCoordinate

        context.addEventHandler('mousebutton', button=0, state=1, function=hit)
        for frame in range(12):
            if 2 <= frame <= 4:
                event = MouseButtonEvent()
                event.button, event.state, event.modifiers = 0, 1, (0, 0, 0)
                event.pickPoint = (SIZE // 2, SIZE // 2)
                context.addPickEvent(event)
                context.triggerPick()
            context.OnDraw(force=1)
        context.flushPendingPicks()
    return found


@pytest.mark.usefixtures('core')
def test_a_pick_reaches_the_first_opaque_voxel():
    node = VolumeData(dimensions=(6, 6, 6), voxels=ball())
    found = _pick(node)
    assert found['node'] is node
    assert found['point'][2] < 1.0


@pytest.mark.usefixtures('core')
def test_a_pick_passes_through_the_volumes_transparent_parts():
    node = VolumeData(dimensions=(6, 6, 6), voxels=uniform(0))
    assert _pick(node).get('node') is not node
