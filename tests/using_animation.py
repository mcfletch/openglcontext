#! /usr/bin/env python
'''=Animating a cannon-ball=

[using_animation.py-screen-0001.png Screenshot]

A small artillery game on two towers.  A cannon stands on the left-hand
tower and the target is the right-hand one; each course puts the towers at a
new height and distance.  You set the cannon's bearing, elevation and power
with the keys, fire, and watch the ball fly its parabola.  A ball that lands
on the target's top wins; any other shot is reported as short, past, left or
right, and by how many metres, and you adjust and fire again.

Keys:

 * `q` and `a` -- turn the cannon left and right
 * `w` and `s` -- raise and lower the barrel
 * `e` and `d` -- more and less power
 * `space` -- fire, and after a win start a new course

Each pair is one column of the keyboard: the upper key turns left, raises or
adds power, and the lower key does the opposite.

The window shows four views of one scene: the plan, the front and the left
elevation, each fitted to the towers, and the view along the barrel, which
turns as the cannon does.

The game's rules are plain Python with no GL in them, so the arithmetic can
be read, and tested, apart from the window.  What the scene does is the
animation: a `Timer` delivers an event every frame, and the handler sets
the ball's `translation` to where the parabola puts it.

:doc:`using_physics` plays the same game with the physics engine flying the
ball, and no parabola in the script.
'''
import math
from dataclasses import dataclass, field

from OpenGLContext import entropy
from OpenGLContext.context import MultiViewContext as BaseContext
from OpenGLContext.events import systemtime
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph import surfaces
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Coordinate, DirectionalLight, IndexedLineSet, Material,
    Shape, Transform, sceneGraph,
)
from OpenGLContext.scenegraph.physicalmaterial import PhysicalMaterial
from OpenGLContext.ui.hudwidgets import HUDLayer, TextBlock
from OpenGLContext.viewer.environment import sky_background

#: The window is larger than most of these scripts', since it holds four views.
SIZE = (900, 700)

#: Metres per second squared, downward.
GRAVITY = 9.81

#: Radius of the ball, and the distance from the barrel's pivot to its mouth,
#: in metres.
BALL_RADIUS = 0.3
BARREL = 2.0

#: Seconds between the samples a flight is traced at.
STEP = 1.0 / 120.0

#: Half the width of each tower, in metres.  The target is small: at forty
#: metres it is under two degrees across.
CANNON_HALF, TARGET_HALF = 2.0, 1.25

#: The longest a flight is followed, in seconds.
LONGEST = 60.0

#: What one key press changes: degrees of bearing and elevation, and metres per
#: second of power.
TURN, RAISE, PUSH = 0.2, 0.2, 0.2

#: How far the aim may be moved: bearing either side of straight ahead and the
#: elevation, in degrees, and the power in metres per second.
BEARING_LIMIT = (-60.0, 60.0)
ELEVATION_LIMIT = (-10.0, 85.0)
POWER_LIMIT = (5.0, 40.0)

#: What each aiming key changes.
AIM_KEYS = {
    'q': dict(bearing=TURN), 'a': dict(bearing=-TURN),
    'w': dict(elevation=RAISE), 's': dict(elevation=-RAISE),
    'e': dict(power=PUSH), 'd': dict(power=-PUSH),
}


@dataclass(frozen=True)
class Platform:
    """A square tower: centre on the ground plane, height and half its width."""

    x: float
    z: float
    top: float
    half: float = 2.5

    def holds(self, point, margin=0.0):
        """Whether ``point`` is inside the tower, grown by ``margin`` metres."""
        return (abs(point[0] - self.x) <= self.half + margin
                and abs(point[2] - self.z) <= self.half + margin
                and point[1] <= self.top + margin)


@dataclass(frozen=True)
class Verdict:
    """How a shot ended: ``hit``, ``short``, ``past``, ``left`` or ``right``.

    ``distance`` is how many metres the ball landed outside the target's
    edge, 0 for a hit.
    """

    kind: str
    distance: float = 0.0

    @property
    def won(self):
        return self.kind == 'hit'

    def message(self):
        if self.won:
            return 'Direct hit!  Space for a new course.'
        return '%s by %.1f m' % (self.kind.capitalize(), self.distance)


@dataclass
class Flight:
    """The path of one shot: the ball's position every ``STEP`` seconds.

    The ball moves as ``position = start + velocity * t + gravity * t**2 / 2``,
    a parabola, and the path ends where it enters a tower or reaches the
    ground.
    """

    points: list = field(default_factory=list)
    verdict: Verdict = Verdict('short')

    @property
    def duration(self):
        return (len(self.points) - 1) * STEP

    def at(self, elapsed):
        """The ball's position ``elapsed`` seconds after it left the barrel."""
        place = max(0.0, elapsed) / STEP
        low = min(int(place), len(self.points) - 1)
        high = min(low + 1, len(self.points) - 1)
        along = place - low
        return tuple(a + (b - a) * along
                     for a, b in zip(self.points[low], self.points[high]))


def direction(bearing, elevation):
    """The unit vector a barrel at ``bearing`` and ``elevation`` degrees points along.

    Bearing 0 is along +x, the line between the towers, and a positive
    bearing turns towards -z, which is to the left looking along it.
    """
    turn, rise = math.radians(bearing), math.radians(elevation)
    return (math.cos(turn) * math.cos(rise), math.sin(rise),
            -math.sin(turn) * math.cos(rise))


def judge(landing, source, target):
    """The verdict for a ball that came down at ``landing`` and missed ``target``.

    Measured on the line from the cannon's tower to the target: along it is
    past or short, across it is left or right as the cannon sees it, and the
    larger of the two is what is reported.
    """
    run = (target.x - source.x, target.z - source.z)
    length = math.hypot(*run) or 1.0
    ahead = (run[0] / length, run[1] / length)
    offset = (landing[0] - target.x, landing[2] - target.z)
    along = offset[0] * ahead[0] + offset[1] * ahead[1]
    across = offset[0] * -ahead[1] + offset[1] * ahead[0]
    if abs(along) >= abs(across):
        kind, miss = ('past' if along > 0 else 'short'), along
    else:
        kind, miss = ('right' if across > 0 else 'left'), across
    return Verdict(kind, max(0.0, abs(miss) - target.half))


def fly(start, velocity, source, target):
    """The ``Flight`` of a ball leaving ``start`` at ``velocity`` (metres per second).

    It ends when the ball's centre comes within a radius of a tower or the
    ground.  Coming down onto the target's top is a hit, and anything else
    is judged by where it landed.
    """
    points = [tuple(start)]
    for tick in range(1, int(LONGEST / STEP)):
        t = tick * STEP
        point = (start[0] + velocity[0] * t,
                 start[1] + velocity[1] * t - GRAVITY * t * t / 2.0,
                 start[2] + velocity[2] * t)
        last = points[-1]
        if target.holds(point, BALL_RADIUS):
            if last[1] > target.top + BALL_RADIUS:
                points.append((point[0], target.top + BALL_RADIUS, point[2]))
                return Flight(points, Verdict('hit'))
            points.append(point)
            return Flight(points, judge(point, source, target))
        if source.holds(point, BALL_RADIUS) or point[1] <= BALL_RADIUS:
            point = (point[0], max(point[1], BALL_RADIUS), point[2])
            points.append(point)
            return Flight(points, judge(point, source, target))
        points.append(point)
    return Flight(points, judge(points[-1], source, target))


def barrel():
    '''The barrel as a closed solid: a tube and a disc over each end.

    A cylinder is only its curved face, and from inside the barrel's mouth or
    behind its breech that face is culled, so the camera on the cannon would
    see through it.  The tube stands along y, centred, and the caller turns it
    along x.
    '''
    sides, radius = 20, 0.22
    half = BARREL / 2.0
    return surfaces.merge([
        surfaces.cylinder(radius, BARREL, sides=sides),
        surfaces.placed(surfaces.polygon(radius, sides), (0, half, 0), (1, 0, 0, -math.pi / 2)),
        surfaces.placed(surfaces.polygon(radius, sides), (0, -half, 0), (1, 0, 0, math.pi / 2)),
    ])


def _turned(axis, degrees):
    '''The 3x3 rotation matrix for ``degrees`` about the y or z axis.'''
    cosine, sine = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    if axis == 'y':
        return ((cosine, 0, sine), (0, 1, 0), (-sine, 0, cosine))
    return ((cosine, -sine, 0), (sine, cosine, 0), (0, 0, 1))


def _product(left, right):
    return tuple(tuple(sum(left[i][k] * right[k][j] for k in range(3)) for j in range(3))
                 for i in range(3))


def barrel_camera(pivot, bearing, elevation):
    '''Where a camera behind and above the barrel stands, and how it is turned.

    Returns the position and a VRML97 orientation ``(x, y, z, radians)``.  A
    camera looks along -z, so it is first turned a quarter turn to look along
    the barrel's own +x.
    '''
    barrel = _product(_turned('y', bearing), _turned('z', elevation))
    look = _product(barrel, _turned('y', -90.0))
    back = (-1.0, 0.8, 0.0)
    position = tuple(pivot[i] + sum(barrel[i][j] * back[j] for j in range(3))
                     for i in range(3))
    angle = math.acos(min(1.0, max(-1.0, (look[0][0] + look[1][1] + look[2][2] - 1.0) / 2.0)))
    axis = (look[2][1] - look[1][2], look[0][2] - look[2][0], look[1][0] - look[0][1])
    length = math.sqrt(sum(part * part for part in axis))
    if length < 1e-9:
        return position, (0.0, 1.0, 0.0, 0.0)
    return position, (axis[0] / length, axis[1] / length, axis[2] / length, angle)


@dataclass
class Aim:
    """Where the cannon points and how hard it fires."""

    bearing: float = 0.0
    elevation: float = 20.0
    power: float = 10.0

    def adjust(self, bearing=0.0, elevation=0.0, power=0.0):
        self.bearing = min(max(self.bearing + bearing, BEARING_LIMIT[0]), BEARING_LIMIT[1])
        self.elevation = min(max(self.elevation + elevation, ELEVATION_LIMIT[0]),
                             ELEVATION_LIMIT[1])
        self.power = min(max(self.power + power, POWER_LIMIT[0]), POWER_LIMIT[1])

    def velocity(self):
        return tuple(self.power * part for part in direction(self.bearing, self.elevation))


class Game:
    """The rules: two towers, the aim, and a shot in the air or not.

    ``state`` is ``aiming`` until the cannon fires, ``flying`` while the ball
    is in the air, then ``aiming`` again after a miss or ``won`` after a hit.
    Nothing here draws or reads a clock: `tick` is given the seconds that
    have passed.
    """

    def __init__(self, rng=None):
        self.rng = rng or entropy.randomizer('cannon')
        self.aim = Aim()
        self.new_course()

    def new_course(self):
        """Two towers at random heights, distances and offsets across the line."""
        rng = self.rng
        self.cannon = Platform(rng.uniform(-35, -20), rng.uniform(-10, 10),
                               rng.uniform(2.0, 5.0), CANNON_HALF)
        self.target = Platform(rng.uniform(20, 35), rng.uniform(-10, 10),
                               rng.uniform(1.0, 8.0), TARGET_HALF)
        self.state = 'aiming'
        self.flight: Flight | None = None
        self.elapsed = 0.0
        self.message = 'Aim, then fire with the space bar.'

    @property
    def pivot(self):
        """Where the barrel turns: above the cannon's tower."""
        return (self.cannon.x, self.cannon.top + 0.9, self.cannon.z)

    @property
    def muzzle(self):
        """The centre of the mouth of the barrel."""
        reach = direction(self.aim.bearing, self.aim.elevation)
        return tuple(p + BARREL * r for p, r in zip(self.pivot, reach))

    @property
    def ball(self):
        """Where the ball is: in the flight, or in the mouth of the barrel."""
        if self.flight is None:
            return self.muzzle
        return self.flight.at(self.elapsed)

    def bounds(self):
        """``(minimum, maximum)``, the box round the towers and the sky over them."""
        high = max(self.cannon.top, self.target.top) + 25.0
        reach = max(self.cannon.half, self.target.half) + 6.0
        low_x = min(self.cannon.x, self.target.x) - reach
        high_x = max(self.cannon.x, self.target.x) + reach
        low_z = min(self.cannon.z, self.target.z) - reach
        high_z = max(self.cannon.z, self.target.z) + reach
        return ((low_x, 0.0, low_z), (high_x, high, high_z))

    def adjust(self, **change):
        """Move the aim, unless a ball is in the air."""
        if self.state == 'flying':
            return
        self.aim.adjust(**change)
        self.message = ''

    def fire(self):
        """Fire from the muzzle; after a win, lay out a new course instead."""
        if self.state == 'won':
            self.new_course()
        elif self.state == 'aiming':
            self.flight = fly(self.muzzle, self.aim.velocity(), self.cannon, self.target)
            self.elapsed = 0.0
            self.state = 'flying'
            self.message = ''

    def tick(self, seconds):
        """Carry the ball ``seconds`` further; the verdict is the message at the end."""
        flight = self.flight
        if self.state != 'flying' or flight is None:
            return
        self.elapsed += seconds
        if self.elapsed >= flight.duration:
            self.elapsed = flight.duration
            verdict = flight.verdict
            self.state = 'won' if verdict.won else 'aiming'
            self.message = verdict.message()


class TestContext(BaseContext):
    def OnInit(self):
        '''The rules are a `Game`; the context builds the scene from its
        towers and then keeps the scene in step with it.'''
        BaseContext.OnInit(self)
        self.game = Game()
        game = self.game
        '''=Surfaces=

        The towers wear brick and marble and the ground sandstone.  A
        surface is laid out by the metre, so the pattern keeps its size
        however tall a tower is.  The ball is polished steel.'''
        brick = surfaces.pbr_material(surfaces.brick(256))
        marble = surfaces.pbr_material(surfaces.checkered_marble(256, tiles=2))
        sand = surfaces.pbr_material(surfaces.sandstone(256))
        steel = PhysicalMaterial(baseColor=surfaces.STEEL, metallic=1.0, roughness=0.25)
        bronze = PhysicalMaterial(baseColor=surfaces.BRONZE, metallic=1.0, roughness=0.35)
        bullseye = PhysicalMaterial(baseColor=(0.8, 0.08, 0.06), metallic=0.0, roughness=0.5)
        self.materials = (brick, marble, bullseye)
        ground = Transform(translation=(0, 0, 0), rotation=(1, 0, 0, -math.pi / 2), children=[
            surfaces.shape(surfaces.panel(160, 80, repeat=4.0), sand),
        ])
        '''The two towers and the mark on the target are the course, which
        is a group of its own so that a new one replaces its children.'''
        self.course = Transform()
        children = [
            sky_background(),
            DirectionalLight(direction=(-0.4, -0.8, -0.5)),
            ground,
            self.course,
        ]
        '''=Aiming the cannon=

        Two `Transform` nodes hold the barrel: the outer turns it about the
        vertical for the bearing, the inner tilts it for the elevation.
        Rotations are VRML97's `(x, y, z, radians)`.  The window's camera is
        the view platform, which is moved to sit behind the barrel and look
        along it each time the aim changes.'''
        self.base = surfaces.shape(surfaces.block((1.4, 0.9, 1.4)), bronze)
        self.tilt = Transform(children=[
            surfaces.shape(barrel(), bronze,
                           translation=(BARREL / 2.0, 0, 0),
                           rotation=(0, 0, 1, -math.pi / 2)),
        ])
        self.turn = Transform(children=[self.tilt])
        '''=The ball and its path=

        The ball is a `Transform` that the handler moves.  The path is an
        `IndexedLineSet` whose points are written once a shot is over,
        so the other views show where it went.'''
        self.ball = surfaces.shape(surfaces.sphere(BALL_RADIUS), steel)
        self.trail = Coordinate(point=[game.muzzle, game.muzzle])
        self.line = IndexedLineSet(coord=self.trail, coordIndex=[0, 1, -1])
        children += [
            self.base, self.turn, self.ball,
            Shape(geometry=self.line, appearance=Appearance(
                material=Material(emissiveColor=(1.0, 0.8, 0.2), diffuseColor=(0, 0, 0)))),
        ]
        self.sg = sceneGraph(children=children)
        self.hud()
        '''=Keys=

        A held key repeats, so the aim moves for as long as it is down.'''
        for name in AIM_KEYS:
            self.addEventHandler('keypress', name=name, function=self.OnAim)
        self.addEventHandler('keypress', name=' ', function=self.OnFire)
        '''=The clock=

        The timer repeats, and `fraction` arrives every frame.  How far the
        ball has gone is the time since the last frame, from the engine's own
        clock, so a capture that steps the clock steps the ball with it.'''
        self.timer = Timer(duration=1.0, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        self.last = systemtime.systemTime()
        self.shown = None
        self.lay_out()
        print(__doc__)

    def lay_out(self):
        '''Build the scene's towers and put the cannon on its tower.  Runs
        for the first course and every one after it.'''
        game = self.game
        brick, marble, bullseye = self.materials
        self.course.children = [
            self.tower(game.cannon, brick),
            self.tower(game.target, marble),
            surfaces.shape(
                surfaces.block((game.target.half * 1.6, 0.06, game.target.half * 1.6)),
                bullseye,
                translation=(game.target.x, game.target.top + 0.03, game.target.z)),
        ]
        self.base.translation = (game.cannon.x, game.cannon.top + 0.45, game.cannon.z)
        self.turn.translation = game.pivot
        self.trail.point = [game.muzzle, game.muzzle]
        self.line.coordIndex = [0, 1, -1]
        self.update()

    def tower(self, platform, material):
        """A tower from the ground to its top, wearing ``material``."""
        return surfaces.shape(
            surfaces.block((platform.half * 2, platform.top, platform.half * 2), repeat=2.0),
            material, translation=(platform.x, platform.top / 2.0, platform.z))

    def hud(self):
        '''=The heads-up display=

        Text over the scene is a `TextBlock` on a `HUDLayer`, which is drawn
        over every view.  A `TextBlock` takes its text as lines, and the
        handler rewrites them.'''
        self.readout = TextBlock(anchor='bottom-right', align='right', lines=[])
        self.addHUDLayer(HUDLayer(children=[self.readout]))

    def setupViews(self):
        '''=Four views=

        A `MultiViewContext` shows the plan, the front and the left elevation
        in orthographic views and, in the fourth, what the window's camera
        sees, which here is a camera placed behind the barrel.  The three
        elevations are fitted to the box round the towers each time a course
        is laid out.'''
        self.startViews(arrangement='quad', bounds=lambda: self.game.bounds())

    def OnAim(self, event):
        self.game.adjust(**AIM_KEYS[event.name])
        self.update()

    def OnFire(self, event):
        was = self.game.state
        self.game.fire()
        if was == 'won':
            '''The towers are scene nodes, so a new course is new nodes, and
            the three elevations are fitted to it again.'''
            self.lay_out()
            self.frameViews()
        self.update()

    def OnFraction(self, event):
        now = systemtime.systemTime()
        self.game.tick(now - self.last)
        self.last = now
        self.update()

    def update(self):
        '''Write what the game says into the scene.  Setting a field is the
        whole of animating: it marks what must be redrawn.'''
        game = self.game
        aim = (game.aim.bearing, game.aim.elevation)
        if aim != self.shown:
            self.shown = aim
            self.turn.rotation = (0, 1, 0, math.radians(aim[0]))
            self.tilt.rotation = (0, 0, 1, math.radians(aim[1]))
        position, orientation = barrel_camera(game.pivot, *aim)
        self.platform.setPosition(position)
        self.platform.setOrientation(orientation)
        self.ball.translation = game.ball
        if game.state == 'aiming' and game.flight is not None:
            self.trail.point = game.flight.points[::6] + [game.flight.points[-1]]
            self.line.coordIndex = list(range(len(self.trail.point))) + [-1]
        self.readout.lines = [
            'q a  bearing    %5.1f deg' % game.aim.bearing,
            'w s  elevation  %5.1f deg' % game.aim.elevation,
            'e d  power      %5.1f m/s' % game.aim.power,
            'space  fire',
            '',
            game.message,
        ]


if __name__ == "__main__":
    TestContext.ContextMainLoop(definition={'renderer': 'pbr', 'size': SIZE})
