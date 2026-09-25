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
from OpenGLContext.passes.reflectionplanner import ReflectedView, ReflectionPlanner, view_key
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
    record = _mirror(reflector=PlanarReflector(distortion=0.3, replace=True,
                                               reflectance=0.8))
    plan = ReflectionPlanner().plan([_frame([record])], ATLAS, BIG)
    lookup = plan.lookup(plan.frames[0], record)
    assert lookup.distortion == pytest.approx(0.3)
    assert lookup.reflectance == pytest.approx(0.8)
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

from OpenGLContext.passes.reflectionplanner import SETTLE_FRAMES


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


# --- a mirror seen in a mirror ------------------------------------------------

def _behind(z=6.0):
    """A mirror behind the camera, facing the one in front of it: only that
    mirror's reflection sees it."""
    mesh = PBRMesh(positions=QUAD, indices=QUAD_INDICES)
    material = PBRMaterial(metallic=1.0, roughness=0.0,
                           reflector=PlanarReflector(interval=3))
    tmatrix = np.diag([-2.0, 2.0, -2.0, 1.0]).astype('f')
    tmatrix[3, :3] = (0.0, 1.5, z)
    shape = Shape(geometry=mesh, appearance=Appearance(material=material))
    return ((False,), None, tmatrix, None, _Path(('behind', z)), shape)


def _by_path(plan, record):
    return [draw for draw in plan.draws if draw.record[4] is record[4]]


def test_a_mirror_seen_only_in_another_mirror_is_drawn_for_that_mirror():
    """The mirror behind the camera shows in the front mirror's reflection with
    a reflection of its own, drawn from the front mirror's camera."""
    front, back = _mirror(), _behind()
    plan = _settled_planner().plan([_frame([front])], ATLAS, BIG,
                                   inside=lambda frame: [front, back])
    [outer], [inner] = _by_path(plan, front), _by_path(plan, back)
    assert inner.frame.view is outer.view
    assert (outer.depth, inner.depth) == (1, 2)
    assert plan.lookups[(view_key(outer.view), id(back[4]))] is not None
    assert (view_key(outer.view), id(front[4])) not in plan.lookups


def test_mirrors_are_looked_for_in_a_mirrors_view_and_no_deeper():
    front, back = _mirror(), _behind()
    looked = []

    def inside(frame):
        looked.append(frame)
        return [front, back]

    _settled_planner().plan([_frame([front])], ATLAS, BIG, inside=inside)
    assert len(looked) == 1
    assert looked[0].view.source is VIEW


def test_a_mirrors_view_is_the_same_view_from_frame_to_frame():
    """Its identity keys the reflections read inside it, a frame later."""
    planner = _settled_planner()
    front, back = _mirror(), _behind()
    views = [_by_path(planner.plan([_frame([front])], ATLAS, BIG,
                                   inside=lambda frame: [back]), front)[0].view
             for _ in range(2)]
    assert views[0] is views[1]
    assert views[0].name == VIEW.name


def test_mirrors_facing_each_other_are_followed_to_the_bounce_limit():
    """Each chain of mirrors is looked through with its own camera."""
    front, back = _mirror(), _behind()
    looked = []

    def inside(frame):
        looked.append(frame)
        return [front, back]

    plan = _settled_planner().plan([_frame([front])], ATLAS, BIG, inside=inside,
                                   bounces=3)
    assert [frame.view.depth for frame in looked] == [1, 2]
    assert not np.allclose(looked[0].modelView, looked[1].modelView)
    assert sorted(draw.depth for draw in plan.draws) == [1, 2, 3]


def test_one_bounce_looks_for_no_mirror_in_a_mirror():
    looked = []
    _settled_planner().plan([_frame([_mirror()])], ATLAS, BIG,
                            inside=lambda frame: looked.append(frame) or [],
                            bounces=1)
    assert looked == []


def test_a_view_drawn_without_a_mirrors_reflection_is_drawn_again_once_it_has_one():
    """A reflection not yet drawn is shown as the probe meanwhile, and the view
    showing it is not held back waiting for it."""
    planner = _settled_planner()
    front, back = _mirror(reflector=PlanarReflector(interval=100)), _behind()
    one = Budget(views=1, separate_views=1, texels=10 ** 9)

    def plan(budget):
        return planner.plan([_frame([front])], ATLAS, budget, inside=lambda frame: [back])

    first = plan(one)
    [outer] = first.draws
    inner_key = (view_key(outer.view), id(back[4]))
    planner.drawn_without(outer.key, [inner_key])
    second = plan(one)
    assert [draw.key for draw in second.draws] == [inner_key]
    waiting = {c.key: c for c in second.candidates}[outer.key]
    assert waiting.valid
    third = plan(NOTHING)
    assert not {c.key: c for c in third.candidates}[outer.key].valid


def test_a_mirror_in_a_mirror_is_allowed_by_where_the_viewer_stands():
    """Zones switch mirrors on and off for the camera inside them; a mirror
    seen in a mirror is asked about the viewer, not the reflected camera."""
    planner = _settled_planner()
    front, back = _mirror(), _behind()
    asked = []
    planner.allowed = lambda record, eye: asked.append(tuple(np.round(eye, 6))) or True
    planner.plan([_frame([front])], ATLAS, BIG, inside=lambda frame: [back])
    assert len(asked) == 2
    assert asked[0] == asked[1] == pytest.approx((0.0, 1.6, 3.0))


# --- coplanar mirrors ---------------------------------------------------------------

def test_coplanar_mirrors_sharing_a_reflector_are_one_reflection():
    """A wall of mirrors one reflector tunes is one mirror: one view, read by all."""
    shared = PlanarReflector(interval=3)
    left, right = _mirror(-1.5, reflector=shared), _mirror(1.5, reflector=shared)
    plan = _settled_planner().plan([_frame([left, right])], ATLAS, BIG)
    assert len(plan.draws) == 1
    first, second = plan.lookup(plan.frames[0], left), plan.lookup(plan.frames[0], right)
    assert first is not None and first.transform == second.transform
    crop = plan.draws[0].mirror.crop
    single = ReflectionPlanner().plan([_frame([left])], ATLAS, BIG).draws[0].mirror.crop
    assert crop[2] - crop[0] > single[2] - single[0]


def test_coplanar_mirrors_with_reflectors_of_their_own_are_two():
    left, right = _mirror(-1.5), _mirror(1.5)
    assert len(_settled_planner().plan([_frame([left, right])], ATLAS, BIG).draws) == 2


def test_a_mirror_a_step_behind_another_is_its_own_even_sharing_a_reflector():
    shared = PlanarReflector(interval=3)
    front, back = _mirror(-1.5, reflector=shared), _mirror(1.5, reflector=shared)
    back[2][3, 2] -= 0.5
    assert len(_settled_planner().plan([_frame([front, back])], ATLAS, BIG).draws) == 2


def test_a_group_leaves_every_one_of_its_mirrors_out_of_its_own_view():
    shared = PlanarReflector(interval=3)
    left, right = _mirror(-1.5, reflector=shared), _mirror(1.5, reflector=shared)
    plan = _settled_planner().plan([_frame([left, right])], ATLAS, BIG,
                                   inside=lambda frame: [left, right])
    assert [draw.depth for draw in plan.draws] == [1]


def test_a_view_waiting_on_a_group_is_drawn_again_when_any_of_it_arrives():
    """Drawn without a group's reflection, told so by a member's key, and drawn
    again once the group's is drawn."""
    planner = _settled_planner()
    front = _mirror(reflector=PlanarReflector(interval=100))
    shared = PlanarReflector(interval=100)
    back = [_behind(), _behind(6.0)]
    back[1][2][3, 0] += 3.0
    back = [(record[0], record[1], record[2], record[3], _Path(('behind', i)), record[5])
            for i, record in enumerate(back)]
    for record in back:
        record[5].appearance.material.reflector = shared
    one = Budget(views=1, separate_views=1, texels=10 ** 9)
    first = planner.plan([_frame([front])], ATLAS, one, inside=lambda frame: back)
    [outer] = first.draws
    member = (view_key(outer.view), id(back[1][4]))
    planner.drawn_without(outer.key, [member])
    planner.plan([_frame([front])], ATLAS, one, inside=lambda frame: back)
    third = planner.plan([_frame([front])], ATLAS, NOTHING, inside=lambda frame: back)
    assert not {c.key: c for c in third.candidates}[outer.key].valid


def test_a_mirror_view_is_never_keyed_as_one_that_came_before_it():
    """A mirror's view is made as it comes into view and dropped as it leaves;
    one made later must not read the reflections kept for one dropped, which
    an address reused for the new object would hand it."""

    keys = set()
    for index in range(200):
        view = ReflectedView(VIEW, index, np.zeros(3))
        keys.add(view_key(view))
        del view
    assert len(keys) == 200
    assert view_key(VIEW) == view_key(VIEW)


# --- values code set on a reflector ----------------------------------------------

@pytest.mark.parametrize('field, value', [
    ('scale', float('nan')), ('scale', float('inf')), ('scale', -1.0),
    ('interval', 0), ('interval', -5), ('priority', float('nan')),
    ('distortion', float('nan')), ('reflectance', float('inf')),
])
def test_a_reflector_field_no_mirror_can_have_is_planned_within_bounds(field, value):
    """An application writing NaN into a field gets a mirror drawn at the
    field's default or bound, not a planner raising every frame."""
    reflector = PlanarReflector(interval=3)
    setattr(reflector, field, value)
    record = _mirror(reflector=reflector)
    frame = _frame([record])
    plan = ReflectionPlanner().plan([frame], ATLAS, BIG)
    draw, = plan.draws
    lookup = plan.lookup(frame, record)
    assert np.isfinite(lookup.distortion) and np.isfinite(lookup.reflectance)
    assert 0.0 <= lookup.reflectance <= 1.0
    assert draw.mirror.size[0] >= 8


# --- a mirror the budget cannot draw -------------------------------------------------

def _close_up():
    """A mirror filling the view: its tile is the whole view and its guard band."""
    record = _mirror(reflector=PlanarReflector(interval=3, scale=1.0))
    return record, _frame([record], eye=(0.0, 1.5, -4.0))


def test_a_mirror_filling_the_view_is_drawn_within_a_short_budget():
    record, frame = _close_up()
    planner = _settled_planner()
    tight = Budget(views=16, separate_views=4, texels=5000)
    plan = planner.plan([frame], ATLAS, tight)
    draw, = plan.draws
    assert draw.tile.width * draw.tile.height <= 5000 + 2 * 8 * max(draw.tile.rect[2:])
    assert plan.lookup(frame, record) is not None
    assert not planner.plan([_close_up()[1]], ATLAS, tight).unfinished


def test_a_mirror_no_budget_can_draw_does_not_ask_for_frames_forever():
    record, frame = _close_up()
    planner = _settled_planner()
    plan = planner.plan([frame], ATLAS, Budget(views=16, separate_views=4, texels=10))
    assert plan.draws == [] and not plan.unfinished


# --- tiles a repack moved --------------------------------------------------------------

@pytest.mark.parametrize('atlas, texels', [((112, 64), 2304), ((144, 64), 4608)])
def test_tiles_a_repack_moved_are_redrawn_only_within_the_budget(atlas, texels):
    """A repack loses what the moved tiles held; redrawing them is charged to
    the frame's texels like any other mirror view, and one left undrawn is
    not read. Three mirrors, then one of them replaced by a larger one in an
    atlas too small to take it without packing again."""
    planner = _settled_planner()
    a, b, c = (_mirror(x, reflector=PlanarReflector(interval=100)) for x in (-2.5, 0.0, 2.5))
    planner.plan([_frame([a, b, c])], atlas, BIG)
    before = planner.packer.tiles
    newcomer = _mirror(0.0, reflector=PlanarReflector(interval=100, scale=1.0))
    newcomer[2][3, 1] = 3.2
    budget = Budget(views=16, separate_views=4, texels=texels)
    plan = planner.plan([_frame([a, c, newcomer])], atlas, budget)
    after = planner.packer.tiles
    moved = {key for key in before if key in after and before[key] != after[key]}
    drawn = {draw.key for draw in plan.draws}
    assert plan.texels <= budget.texels
    assert all(key in drawn or key not in plan.lookups for key in moved)


# --- a held tile the budget passes over ------------------------------------------------

def test_a_reflection_to_be_redone_is_read_until_it_is():
    """The next frame with room redraws it; until then what it shows is right."""
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=100))
    first = planner.plan([_frame([record])], ATLAS, BIG)
    planner.redo([first.draws[0].key])
    later = planner.plan([_frame([record])], ATLAS, NOTHING)
    assert later.lookup(later.frames[0], record) == first.lookup(first.frames[0], record)
    assert later.unfinished


def test_a_mirror_whose_crop_moved_reads_its_old_tile_until_redrawn():
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=100))
    first = planner.plan([_frame([record])], ATLAS, BIG)
    later = planner.plan([_frame([record], eye=(2.5, 1.6, 1.0))], ATLAS, NOTHING)
    assert not later.candidates[0].valid
    assert later.lookup(later.frames[0], record).matrix == \
        first.lookup(first.frames[0], record).matrix


# --- how many mirror views a frame plans ---------------------------------------------------

def test_facing_mirrors_stop_being_followed_at_a_multiple_of_the_view_budget():
    """A hall of facing mirrors at six bounces plans no more than the views
    the budget could draw several times over."""
    from OpenGLContext.passes.reflectionplanner import CANDIDATES_PER_VIEW
    records = [_mirror(x) for x in (-2.0, 0.0, 2.0)] + [_behind(6.0)]
    records[3][2][3, 0] = 0.0
    budget = Budget(views=2, separate_views=2, texels=10 ** 9)
    plan = _settled_planner().plan([_frame(records[:3])], ATLAS, budget,
                                   inside=lambda frame: records, bounces=6)
    assert len(plan.candidates) <= CANDIDATES_PER_VIEW * budget.views + len(records)


def test_planes_either_side_of_a_rounding_boundary_are_one_plane():
    """Coplanar is a tolerance, not a rounding: a tenth of a millimetre apart
    is one plane wherever it falls."""
    shared = PlanarReflector(interval=3)
    left, right = _mirror(-1.5, reflector=shared), _mirror(1.5, reflector=shared)
    left[2][3, 2] = -5.00049
    right[2][3, 2] = -5.00051
    plan = _settled_planner().plan([_frame([left, right])], ATLAS, BIG)
    assert len(plan.draws) == 1


# --- what a mirror view draws ---------------------------------------------------------

def _front_and_back(planner, budget=BIG):
    front, back = _mirror(reflector=PlanarReflector(interval=100)), _behind()
    plan = planner.plan([_frame([front])], ATLAS, budget, inside=lambda frame: [back])
    outer, = _by_path(plan, front)
    return front, back, plan, outer


def test_a_mirror_view_leaves_out_the_mirror_it_is_the_reflection_of():
    planner = _settled_planner()
    front, back, plan, outer = _front_and_back(planner)
    plain = _mirror(4.0)[:5] + (Shape(geometry=PBRMesh(positions=QUAD,
                                                         indices=QUAD_INDICES)),)
    earlier = {(view_key(outer.view), id(back[4])): object()}
    kept, incomplete = planner.contents(plan, outer, [front, plain, back], earlier)
    assert kept == [plain, back] and not incomplete


def test_a_mirror_whose_reflection_is_drawn_this_frame_is_left_out_until_next():
    planner = _settled_planner()
    front, back, plan, outer = _front_and_back(planner)
    kept, incomplete = planner.contents(plan, outer, [back], {})
    assert kept == [] and incomplete


def test_a_mirror_with_no_reflection_yet_is_drawn_and_the_view_redone_once_it_has_one():
    planner = _settled_planner()
    one = Budget(views=1, separate_views=1, texels=10 ** 9)
    front, back, plan, outer = _front_and_back(planner, one)
    kept, incomplete = planner.contents(plan, outer, [back], {})
    assert kept == [back] and not incomplete
    inner = (view_key(outer.view), id(back[4]))
    assert planner._held[outer.key].missing == {inner}


def test_keeping_only_some_tiles_gives_back_the_rest():
    planner = _settled_planner()
    records = [_mirror(x) for x in (-1.5, 1.5)]
    plan = planner.plan([_frame(records)], ATLAS, BIG)
    keep = plan.draws[0].key
    planner.keep_only({keep})
    assert set(planner._held) == {keep} and set(planner.packer.tiles) == {keep}


def test_the_plan_carries_the_budget_it_was_made_within():
    asked = []

    def budget():
        asked.append(1)
        return BIG

    plan = _settled_planner().plan([_frame([_mirror()])], ATLAS, budget)
    assert plan.budget is BIG and asked == [1]
    assert ReflectionPlanner().plan([_frame([])], ATLAS, budget).budget is None


def test_whether_a_mirror_view_draws_apart_is_asked_of_its_own_camera():
    """Nested mirror views are asked too, each with the mirror's own view."""
    from OpenGLContext.passes.reflection import MirrorView
    asked = []
    front, back = _mirror(), _behind()
    plan = _settled_planner().plan(
        [_frame([front])], ATLAS, Budget(views=16, separate_views=1, texels=10 ** 9),
        separate=lambda mirror: asked.append(mirror) or True,
        inside=lambda frame: [front, back])
    assert len(asked) == 2 and all(isinstance(mirror, MirrorView) for mirror in asked)
    assert len(plan.draws) == 1


def test_a_reflected_view_copied_without_its_source_says_so():
    import copy
    view = ReflectedView(VIEW, 'key', np.zeros(3))
    bare = ReflectedView.__new__(ReflectedView)
    with pytest.raises(AttributeError):
        _ = bare.source
    assert copy.copy(view).source is VIEW


# --- the branches a mirror is left out by ------------------------------------------

def test_a_wireframe_view_looks_for_no_mirror():
    from OpenGLContext.multiview.views import ViewStyle
    view = View(style=ViewStyle(wireframe=True))
    plan = ReflectionPlanner().plan([_frame([_mirror()], view=view)], ATLAS, BIG)
    assert plan.draws == [] and plan.lookups == {}


def test_a_mirror_its_zone_refuses_is_not_drawn():
    planner = ReflectionPlanner()
    planner.allowed = lambda record, eye: False
    assert planner.plan([_frame([_mirror()])], ATLAS, BIG).draws == []


def test_a_bent_mirror_and_a_flattened_one_are_not_drawn():
    bent = _mirror()
    bent[5].geometry.positions = np.array(
        [(-1, -1, 0), (1, -1, 0), (1, 1, 0.5), (-1, 1, 0)], 'f')
    squashed = _mirror(2.0)
    squashed[2][:3, :3] = np.diag([1.0, 1.0, 0.0])
    assert ReflectionPlanner().plan([_frame([bent, squashed])], ATLAS, BIG).draws == []


def test_a_mirror_moved_to_another_plane_is_planned_afresh():
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=100))
    planner.plan([_frame([record])], ATLAS, BIG)
    record[2][3, 2] -= 0.5
    later = planner.plan([_frame([record])], ATLAS, NOTHING)
    assert later.candidates[0].age is None
    assert later.lookup(later.frames[0], record) is None


def test_a_still_camera_has_no_drift():
    planner = _settled_planner()
    record = _mirror(reflector=PlanarReflector(interval=100))
    planner.plan([_frame([record])], ATLAS, BIG)
    later = planner.plan([_frame([record])], ATLAS, NOTHING)
    assert later.candidates[0].valid and later.candidates[0].drift == 0.0
