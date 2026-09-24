"""A frame's mirrors, from the views' draw lists to what is drawn and read; no GL.

:class:`ReflectionPlanner` is the part of the reflection pass a test can put
under a microscope: given the frame's views, it says which mirror views to
draw into which tiles, and what each mirror in each view reads.
"""
import numpy as np
import pytest

from OpenGLContext.multiview.strategy import ViewFrame
from OpenGLContext.multiview.views import View
from OpenGLContext.passes import reflection
from OpenGLContext.passes.reflectionplanner import ReflectionPlanner
from OpenGLContext.passes.reflectiontiles import Budget
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.scenegraph.shape import Shape

QUAD = np.array([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], 'f')
QUAD_INDICES = np.array([0, 1, 2, 0, 2, 3], np.uint32)
RECT = (0, 0, 400, 300)
ATLAS = (512, 512)
BIG = Budget(views=16, separate_views=4, texels=10 ** 9)

#: The view the frames are drawn through: a context's views persist from one
#: frame to the next, and a mirror's tile belongs to one of them.
VIEW = View()


class _Path(tuple):
    """A stand-in node path: an object with an identity of its own."""


def _perspective(near=0.1, far=100.0, fov=1.0, aspect=4 / 3):
    f = 1.0 / np.tan(fov / 2.0)
    return np.array([
        [f / aspect, 0, 0, 0],
        [0, f, 0, 0],
        [0, 0, (far + near) / (near - far), 2 * far * near / (near - far)],
        [0, 0, -1, 0],
    ], 'd').T


def _look_at(eye, target=(0.0, 1.5, -5.0)):
    eye = np.asarray(eye, 'd')
    forward = np.asarray(target, 'd') - eye
    forward /= np.linalg.norm(forward)
    side = np.cross(forward, (0.0, 1.0, 0.0))
    side /= np.linalg.norm(side)
    up = np.cross(side, forward)
    rotation = np.identity(4)
    rotation[:3, 0], rotation[:3, 1], rotation[:3, 2] = side, up, -forward
    translation = np.identity(4)
    translation[3, :3] = -eye
    return translation @ rotation


def _mirror(x=0.0, reflector=None, roughness=0.0, transparent=False):
    mesh = PBRMesh(positions=QUAD, indices=QUAD_INDICES)
    material = PBRMaterial(metallic=1.0, roughness=roughness,
                           reflector=reflector or PlanarReflector(interval=3))
    tmatrix = np.identity(4, 'f')
    tmatrix[3, :3] = (x, 1.5, -5.0)
    shape = Shape(geometry=mesh, appearance=Appearance(material=material))
    return ((transparent,), None, tmatrix, None, _Path(('mirror', x)), shape)


def _frame(records, eye=(0.0, 1.6, 3.0), view=None):
    modelview = _look_at(eye)
    projection = _perspective()
    frame = ViewFrame(view or VIEW, None, RECT, modelview, projection,
                      modelview @ projection, None)
    frame.toRender = list(records)
    return frame


def test_a_frame_without_mirrors_draws_none():
    plan = ReflectionPlanner().plan([_frame([])], ATLAS, BIG)
    assert plan.draws == [] and plan.lookups == {}


def test_a_mirror_in_view_is_drawn_and_read():
    record = _mirror()
    frame = _frame([record])
    plan = ReflectionPlanner().plan([frame], ATLAS, BIG)
    draw, = plan.draws
    assert draw.frame is frame and draw.record is record
    assert draw.mirror.size == (draw.tile.width, draw.tile.height)
    lookup = plan.lookup(frame, record)
    assert lookup is not None
    assert lookup.bounds[0] < lookup.bounds[2] <= 1.0


def test_a_rough_reflector_reflects_the_probe():
    record = _mirror(roughness=reflection.ROUGHEST + 0.1)
    plan = ReflectionPlanner().plan([_frame([record])], ATLAS, BIG)
    assert plan.draws == [] and plan.lookup(plan.frames[0], record) is None


def test_a_mirror_seen_from_behind_is_not_a_candidate():
    record = _mirror()
    plan = ReflectionPlanner().plan([_frame([record], eye=(0.0, 1.5, -9.0))],
                                    ATLAS, BIG)
    assert plan.draws == []


def test_a_transparent_reflector_is_a_mirror_too():
    """Water is blended, and reads its reflection all the same."""
    record = _mirror(transparent=True)
    plan = ReflectionPlanner().plan([_frame([record])], ATLAS, BIG)
    assert len(plan.draws) == 1


def test_a_fresh_tile_is_kept_until_its_interval():
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=3))
    first = planner.plan([_frame([record])], ATLAS, BIG)
    tight = Budget(views=0, separate_views=0, texels=0)
    for _ in range(2):
        later = planner.plan([_frame([record])], ATLAS, tight)
        assert later.draws == []
        assert later.lookup(later.frames[0], record) == first.lookup(first.frames[0], record)


NOTHING = Budget(views=0, separate_views=0, texels=0)


def _settled_planner():
    """A planner past the frames a pass settles in, so what it draws is kept."""
    from OpenGLContext.passes.reflectionplanner import SETTLE_FRAMES
    planner = ReflectionPlanner()
    planner.frame = SETTLE_FRAMES
    return planner


def test_a_mirror_at_its_interval_must_be_drawn_again():
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=2))
    planner.plan([_frame([record])], ATLAS, BIG)
    must = [planner.plan([_frame([record])], ATLAS, NOTHING).candidates[0].must
            for _ in range(3)]
    assert must == [False, True, True]


def test_each_view_reads_its_own_tile_of_one_mirror():
    record = _mirror()
    left = _frame([record], eye=(-2.0, 1.6, 3.0), view=View())
    right = _frame([record], eye=(2.0, 1.6, 3.0), view=View())
    plan = ReflectionPlanner().plan([left, right], ATLAS, BIG)
    assert len(plan.draws) == 2
    assert plan.lookup(left, record) != plan.lookup(right, record)


def test_a_mirror_out_of_view_gives_its_tile_back():
    planner = ReflectionPlanner()
    record = _mirror()
    planner.plan([_frame([record])], ATLAS, BIG)
    plan = planner.plan([_frame([])], ATLAS, BIG)
    assert plan.lookups == {} and planner.packer.tiles == {}


def test_moving_the_camera_far_redraws_even_inside_the_interval():
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=10))
    planner.plan([_frame([record], eye=(0.0, 1.6, 3.0))], ATLAS, BIG)
    still = planner.plan([_frame([record], eye=(0.0, 1.6, 3.0))], ATLAS, NOTHING)
    moved = planner.plan([_frame([record], eye=(0.4, 1.6, 3.0))], ATLAS, NOTHING)
    assert not still.candidates[0].must
    assert moved.candidates[0].must and moved.candidates[0].drift > 1.0


def test_the_lookup_carries_the_reflectors_own_settings():
    record = _mirror(reflector=PlanarReflector(distortion=0.3, replace=True))
    plan = ReflectionPlanner().plan([_frame([record])], ATLAS, BIG)
    lookup = plan.lookup(plan.frames[0], record)
    assert lookup.distortion == pytest.approx(0.3)
    assert lookup.replace
    assert tuple(lookup.normal) == pytest.approx((0.0, 0.0, 1.0))


def test_a_short_budget_draws_the_second_mirror_at_half_scale():
    records = [_mirror(x) for x in (-1.5, 1.5)]
    full = ReflectionPlanner().plan([_frame(records)], ATLAS, BIG)
    texels = max(d.tile.width * d.tile.height for d in full.draws)
    budget = Budget(views=16, separate_views=4, texels=texels + texels // 4 + 64)
    halved = ReflectionPlanner().plan([_frame(records)], ATLAS, budget)
    widths = sorted(d.tile.width for d in halved.draws)
    assert len(halved.draws) == 2
    assert widths[0] <= max(d.tile.width for d in full.draws) // 2 + reflection.TEXEL_STEP


def _minor_and_major():
    """Two mirrors of one size, the second weighted four times the first."""
    return (_mirror(x, reflector=PlanarReflector(interval=100, priority=priority))
            for x, priority in ((2.5, 1.0), (0.0, 4.0)))


def _one_tile_atlas(record):
    """An atlas with room for ``record``'s tile and nothing beside it."""
    tile = ReflectionPlanner().plan([_frame([record])], ATLAS, BIG).draws[0].tile
    return tile.width + 8, tile.height + 8


def test_a_mirror_being_drawn_takes_the_room_of_one_weighted_less():
    """An atlas with room for one tile: the mirror weighted more has it."""
    planner = _settled_planner()
    minor, major = _minor_and_major()
    atlas = _one_tile_atlas(major)
    planner.plan([_frame([minor])], atlas, BIG)
    plan = planner.plan([_frame([minor, major])], atlas, BIG)
    assert [draw.record for draw in plan.draws] == [major]
    assert plan.lookup(plan.frames[0], minor) is None


def test_a_mirror_being_drawn_leaves_one_weighted_more_its_room():
    planner = _settled_planner()
    minor, major = _minor_and_major()
    atlas = _one_tile_atlas(major)
    planner.plan([_frame([major])], atlas, BIG)
    plan = planner.plan([_frame([minor, major])], atlas, BIG)
    assert [draw.record[4] for draw in plan.draws] in ([], [major[4]])
    assert plan.lookup(plan.frames[0], major) is not None
    assert plan.lookup(plan.frames[0], minor) is None


def test_mirrors_the_atlas_cannot_hold_together_do_not_take_turns():
    """A still scene with more mirrors than room settles on the ones it keeps:
    trading tiles every frame shows each mirror reflecting and matte by turns."""
    planner = _settled_planner()
    minor, major = _minor_and_major()
    atlas = _one_tile_atlas(major)
    shown = []
    for _ in range(6):
        plan = planner.plan([_frame([minor, major])], atlas, BIG)
        shown.append({key[1] for key in plan.lookups})
    assert shown[-1] == shown[-2] == shown[-3]
    assert not plan.unfinished


def test_a_mirror_too_large_for_the_room_left_is_drawn_at_half_scale():
    planner = ReflectionPlanner()
    first, second = _mirror(-1.2), _mirror(1.2)
    full = planner.plan([_frame([first])], ATLAS, BIG).draws[0].tile
    tight = (full.width + 8, full.height * 2)     # one full tile, and one halved
    plan = ReflectionPlanner().plan([_frame([first, second])], tight, BIG)
    assert len(plan.draws) == 2
    assert min(draw.tile.height for draw in plan.draws) < full.height


# --- settling, and a frame that is not finished -------------------------------

from OpenGLContext.passes.reflectionplanner import SETTLE_FRAMES  # noqa: E402


def _settled(planner, records, budget=BIG):
    for _ in range(SETTLE_FRAMES):
        planner.plan([_frame(records)], ATLAS, budget)


def test_a_reflection_drawn_while_the_pass_settles_is_drawn_again():
    """Programs compile, textures upload and the probe builds in the first
    frames, and what a mirror view draws then is not a picture to keep."""
    planner = ReflectionPlanner()
    record = _mirror(reflector=PlanarReflector(interval=100))
    first = planner.plan([_frame([record])], ATLAS, BIG)
    assert first.unfinished
    later = planner.plan([_frame([record])], ATLAS, NOTHING)
    assert later.candidates[0].must and not later.candidates[0].valid


def test_once_settled_a_drawn_frame_is_finished():
    planner = ReflectionPlanner()
    record = _mirror(reflector=PlanarReflector(interval=100))
    _settled(planner, [record])
    plan = planner.plan([_frame([record])], ATLAS, BIG)
    assert len(plan.draws) == 1 and not plan.unfinished
    kept = planner.plan([_frame([record])], ATLAS, NOTHING)
    assert not kept.candidates[0].must and not kept.unfinished


def test_a_mirror_left_without_a_reflection_asks_for_another_frame():
    """A still scene with room for one mirror a frame gets the rest drawn."""
    planner = ReflectionPlanner()
    records = [_mirror(x) for x in (-1.5, 0.0, 1.5)]
    one = Budget(views=1, separate_views=1, texels=10 ** 9)
    _settled(planner, records, one)
    finished = []
    for _ in range(6):
        plan = planner.plan([_frame(records)], ATLAS, one)
        finished.append(not plan.unfinished)
    assert finished[-1]
    assert len(planner._held) == 3


def test_reaching_its_interval_does_not_ask_for_a_frame():
    """Redrawing a reflection of a still scene changes nothing."""
    planner = ReflectionPlanner()
    records = [_mirror(x, reflector=PlanarReflector(interval=1)) for x in (-1.5, 1.5)]
    one = Budget(views=1, separate_views=1, texels=10 ** 9)
    _settled(planner, records, BIG)
    planner.plan([_frame(records)], ATLAS, BIG)
    plan = planner.plan([_frame(records)], ATLAS, one)
    assert len(plan.draws) == 1 and not plan.unfinished


def test_a_reflection_drawn_while_settling_says_so_in_its_lookup():
    """A mirror view drawing another mirror must not pass that picture on."""
    planner = ReflectionPlanner()
    record = _mirror()
    first = planner.plan([_frame([record])], ATLAS, BIG)
    assert first.lookup(first.frames[0], record).provisional
    _settled(planner, [record])
    later = planner.plan([_frame([record])], ATLAS, BIG)
    assert not later.lookup(later.frames[0], record).provisional


def test_a_reflection_that_left_out_a_mirror_is_drawn_again():
    """It had nothing to show for the mirror in it; next frame it will."""
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=100))
    first = planner.plan([_frame([record])], ATLAS, BIG)
    planner.redo([first.draws[0].key])
    later = planner.plan([_frame([record])], ATLAS, NOTHING)
    assert later.candidates[0].must and later.unfinished
