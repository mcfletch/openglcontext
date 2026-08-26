#! /usr/bin/env python
'''=HUD widgets (screen furniture over a live world)=

[hud_demo.py-screen-0001.png Screenshot]

One `HUDLayer` from `OpenGLContext.ui.hudwidgets`, holding a game's whole
screen furniture over a lit world.  Nothing in it is interactive: the layer
is never offered an event and the pointer goes through it to the world.
Each widget carries the corner it belongs in rather than a position, and
every measurement in it is in pixels at the reference font size, so the
whole HUD scales with the window.

On screen:

 * *centre* -- a `Crosshair`, cross-and-dot.  Its `spread` opens and closes
   on the clock, which is what a weapon whose accuracy falls off while
   firing writes into.
 * *bottom left* -- two `BarMeter`s stacked in a `HUDGroup`.  Their colour
   comes from where the value sits against `warnFraction` and
   `criticalFraction`, so one bar reads green, amber and red as it falls.
 * *top* -- a `LampRow` of five lives, and a `MessageQueue` beneath it whose
   lines fade out on their own clocks.
 * *bottom right* -- a `Readout`: a nine-slice icon, a label and a number.
   It turns critical of its own accord when the count runs low.
 * *bottom centre* -- a `MiniMap` of the pillar ring, with the player marked
   on it wherever they walk.
 * *top right* -- a `TextBlock`, which is what several lines of prose in a
   corner are drawn with.

The keys:

 * `space` -- fire: the reticule shows a hit mark for a third of a second.
 * `x` -- take a hit: the `DamageIndicator` washes the screen edge the
   player would have to turn towards, the health meter flashes, and a lamp
   goes out.
 * `m` -- post a message into the queue.
 * `v` -- a `ScreenWash` over the whole viewport, on and off.
 * `alt-f` -- the developer overlay, where the frame rate is drawn.  The
   demo registers a section of its own at the top of it.

The usual keys walk around, and the HUD stays where it is while you do.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

import math                                                    # noqa: E402
import tempfile                                                # noqa: E402

from OpenGLContext import testingcontext                       # noqa: E402
from OpenGLContext.events import systemtime                    # noqa: E402
from OpenGLContext.events.timer import Timer                   # noqa: E402
from OpenGLContext.scenegraph.basenodes import (               # noqa: E402
    Appearance, Background, Box, DirectionalLight, Material, Shape, Sphere,
    Transform,
)
from OpenGLContext.ui.hudwidgets import (                      # noqa: E402
    CROSS_DOT, BarMeter, Crosshair, DamageIndicator, HUDGroup, HUDLayer,
    LampRow, MessageQueue, MiniMap, Readout, ScreenWash, TextBlock,
)
from OpenGLContext.ui.skin import NineSlice                     # noqa: E402

BaseContext = testingcontext.getInteractive('glfw')

#: Pillars in the ring the demo walks around, and how far out they stand.
PILLARS, RING = 12, 11.0

#: Lamps in the row, and rounds in a full magazine.
LIVES, MAGAZINE = 5, 60

#: Seconds a full sweep of each meter takes.  Two periods that do not divide
#: into one another, so the pair is never showing the same state twice.
HEALTH_PERIOD, ARMOUR_PERIOD = 9.0, 13.0

#: Where each meter stands when the window opens, out of 100.  Chosen so the
#: first frame already has one meter reading well and one reading low.
HEALTH_START, ARMOUR_START = 64.0, 30.0

#: Rounds spent per second, so the read-out counts down to its critical
#: colour and reloads without anything being pressed.
RATE = 3.0

#: Lines the demo posts to the queue on its own, in turn.
TRAFFIC = [
    'PICKED UP A SHOTGUN',
    'CHECKPOINT',
    'YOU HAVE THE FLAG',
    'ARMOUR LOW',
]

#: Seconds between those.
TRAFFIC_INTERVAL = 2.5

#: Seconds between the hits an opponent the demo never draws lands, and how
#: hard each one is, 0 to 1.  Automatic, so the damage wash is on screen
#: without anyone holding a key down.
INCOMING_INTERVAL, INCOMING = 3.0, 0.85


def sweep(elapsed, period, low, high, start):
    """A value that begins at ``start`` and sweeps between two bounds.

    Where the sweep begins is named rather than given as a phase, because
    what a demo has to say is where its meter stands when the window opens.
    """
    span = float(high - low)
    place = min(1.0, max(-1.0, (start - low) / span * 2.0 - 1.0))
    turn = math.asin(place) + 2.0 * math.pi * elapsed / period
    return low + span * (0.5 + 0.5 * math.sin(turn))


def ammo_icon(directory):
    """Draw the read-out's icon into ``directory`` and return its path.

    Generated rather than shipped: what the icon shows is that a `Readout`
    takes a nine-slice like every other image in the interface, and one
    drawn here proves that with nothing binary to keep in step.
    """
    from PIL import Image, ImageDraw
    image = Image.new('RGBA', (32, 32), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle([10, 11, 21, 29], radius=3, fill=(212, 166, 72, 255))
    draw.polygon([(10, 11), (21, 11), (16, 2)], fill=(240, 218, 156, 255))
    path = os.path.join(directory, 'round.png')
    image.save(path)
    return path


def world():
    """A lit ring of pillars to stand the HUD in front of."""
    children = [
        # A dusk sky rather than a black one: a HUD is drawn over colours
        # nobody controls, and white text against a bright horizon is what
        # the shadow behind every glyph is there for.
        Background(skyColor=[(0.09, 0.13, 0.26), (0.30, 0.31, 0.44),
                             (0.86, 0.55, 0.33)],
                   skyAngle=[1.05, 1.5708],
                   groundColor=[(0.16, 0.16, 0.15)]),
        DirectionalLight(direction=(-0.4, -0.7, -0.6), intensity=0.95),
        DirectionalLight(direction=(0.6, -0.25, 0.7), intensity=0.35,
                         color=(0.55, 0.68, 1.0)),
        Transform(translation=(0.0, -0.2, 0.0), children=[
            Shape(geometry=Box(size=(60.0, 0.4, 60.0)),
                  appearance=Appearance(
                      material=Material(diffuseColor=(0.20, 0.22, 0.19))))]),
    ]
    stone = Material(diffuseColor=(0.62, 0.58, 0.50))
    cap = Material(diffuseColor=(0.30, 0.52, 0.62))
    crate = Material(diffuseColor=(0.44, 0.34, 0.24))
    for index in range(PILLARS):
        angle = 2.0 * math.pi * index / PILLARS
        x, z = RING * math.sin(angle), -RING * math.cos(angle)
        children.append(Transform(translation=(x, 1.5, z), children=[
            Shape(geometry=Box(size=(0.9, 3.0, 0.9)),
                  appearance=Appearance(material=stone))]))
        children.append(Transform(translation=(x, 3.4, z), children=[
            Shape(geometry=Sphere(radius=0.55),
                  appearance=Appearance(material=cap))]))
    # Crates at several depths inside the ring, so the middle of the frame has
    # something near in it as well as something far.
    for x, z, side in ((-3.2, 2.0, 1.1), (2.6, 0.4, 0.8), (-1.4, -4.5, 1.4),
                       (4.4, -2.6, 0.9), (5.6, 3.0, 0.8)):
        children.append(Transform(translation=(x, side / 2.0, z), children=[
            Shape(geometry=Box(size=(side, side, side)),
                  appearance=Appearance(material=crate))]))
    return Transform(children=children)


def ring_route():
    """The pillar ring as a closed polyline in world XZ, for the map."""
    return [(RING * math.sin(2.0 * math.pi * index / PILLARS),
             -RING * math.cos(2.0 * math.pi * index / PILLARS))
            for index in range(PILLARS)]


class TestContext(BaseContext):
    """A world, a HUD layer over it, and a clock driving the readings."""

    initialPosition = (0, 2.2, 8.5)

    def OnInit(self):
        BaseContext.OnInit(self)
        self.sg = world()
        self.buildHUD()
        self.started = systemtime.systemTime()
        #: Which way the next hit comes from: radians from straight ahead,
        #: positive to the right.  Stepped by the golden angle, so no two
        #: consecutive hits light the same edge.
        self.bearing = math.pi / 2.0
        #: Which line of TRAFFIC is posted next.
        self.line = 0
        self.addEventHandler('keypress', name=' ', function=self.OnFire)
        self.addEventHandler('keypress', name='x', function=self.OnHurt)
        self.addEventHandler('keypress', name='m', function=self.OnMessage)
        self.addEventHandler('keypress', name='v', function=self.OnWash)
        # order=5: below 10, which is where the engine's own first section
        # registers, so the demo's numbers are at the top of the plate.
        self.debugOverlay.register('HUD demo', self.debugRows, order=5)
        self.traffic = self.repeating(TRAFFIC_INTERVAL, self.OnMessage)
        self.incoming = self.repeating(INCOMING_INTERVAL, self.OnIncoming)
        # One of each on the first frame, so a demo nobody has touched yet is
        # already showing what a message and a damage wash look like.
        self.messages.post(TRAFFIC[0])
        self.OnIncoming()
        self.updateHUD(self.started)
        print(__doc__)

    def repeating(self, interval, handler):
        """A timer that calls ``handler`` every ``interval`` seconds."""
        timer = Timer(duration=interval, repeating=1)
        timer.addEventHandler('cycle', handler)
        timer.register(self)
        timer.start()
        return timer

    # -- building ---------------------------------------------------------
    def buildHUD(self):
        """Every widget the demo shows, in one layer, each in its own corner."""
        self.crosshair = Crosshair(shape=CROSS_DOT, gap=5, length=8,
                                   thickness=2, dotSize=2)
        self.health = BarMeter(label='HEALTH', value=HEALTH_START)
        self.armour = BarMeter(label='ARMOUR', value=ARMOUR_START,
                               warnFraction=0.45, criticalFraction=0.2)
        icon = NineSlice(url=[ammo_icon(tempfile.mkdtemp(prefix='oglc-hud-'))])
        self.ammo = Readout(label='AMMO', value=str(MAGAZINE), icon=icon,
                            iconSize=22, anchor='bottom-right')
        self.lives = LampRow(anchor='top', count=LIVES, lit=LIVES, lampSize=18,
                             gap=9)
        self.messages = MessageQueue(anchor='top', offset=(0, -44),
                                     duration=4.0, fade=1.2)
        self.damage = DamageIndicator()
        self.wash = ScreenWash(colour=(0.15, 0.45, 0.9))
        self.map = MiniMap(anchor='bottom', size=132)
        self.map.route = ring_route()
        legend = TextBlock(anchor='top-right', align='right', lines=[
            'space  fire', 'x  take a hit', 'm  post a message',
            'v  screen wash', 'alt-f  developer overlay',
        ])
        self.hud = HUDLayer(children=[
            # Drawn in order, so the two full-screen washes go under the
            # readings rather than over them.
            self.wash, self.damage,
            self.crosshair, self.lives, self.messages, self.map, self.ammo,
            legend,
            HUDGroup(anchor='bottom-left', spacing=6,
                     children=[self.health, self.armour]),
        ])
        self.addHUDLayer(self.hud)

    # -- the clock --------------------------------------------------------
    def updateHUD(self, now):
        """Write this instant's readings into the widgets.

        Everything a HUD shows is data on a widget, so a frame's worth of
        work is arithmetic and some assignments; the layer measures and
        paints itself afresh from them.
        """
        elapsed = now - self.started
        self.health.value = sweep(elapsed, HEALTH_PERIOD, 5.0, 100.0,
                                  HEALTH_START)
        self.armour.value = sweep(elapsed, ARMOUR_PERIOD, 0.0, 100.0,
                                  ARMOUR_START)
        # A weapon's accuracy falling off and recovering: extra gap, in
        # reference pixels, rather than a bigger reticule.
        self.crosshair.spread = 3.0 + 3.0 * math.sin(elapsed * 1.7)
        rounds = MAGAZINE - int(elapsed * RATE) % (MAGAZINE + 1)
        self.ammo.value = str(rounds)
        self.ammo.critical = rounds <= 10
        self.map.marks = [tuple(self.platform.position[:3:2]) + ('hudGood',)]

    def OnIdle(self, event=None):
        # The readings are a function of the clock, so a still frame is a
        # stopped one: a HUD demo has to keep asking for frames.
        self.updateHUD(systemtime.systemTime())
        self.triggerRedraw(1)

    # -- what the keys do -------------------------------------------------
    def OnFire(self, event):
        """A shot that connected: the reticule acknowledges it and fades."""
        self.crosshair.hit()
        self.triggerRedraw(1)

    def OnIncoming(self, event=None):
        """A hit from a bearing that moves, so the wash slides round the edges.

        The four edges share each hit in proportion to how much they face it,
        which is what makes an opponent circling the player slide the wash
        from one edge to the next rather than stepping between them.
        """
        self.damage.hurt(self.bearing, intensity=INCOMING)
        self.bearing += 2.39996              # the golden angle, in radians
        self.triggerRedraw(1)

    def OnHurt(self, event=None):
        """A hit, and a life with it: the meter flashes and a lamp goes out."""
        self.OnIncoming()
        # Whoever writes the value asks for the flash, because what is worth
        # flashing about is the game's rule and not the meter's.
        self.health.flash()
        left = int(self.lives.lit) - 1
        self.lives.lit = left if left > 0 else LIVES

    def OnMessage(self, event=None):
        self.messages.post(TRAFFIC[self.line % len(TRAFFIC)])
        self.line += 1
        self.triggerRedraw(1)

    def OnWash(self, event):
        """A colour over the whole viewport: the view itself has changed."""
        self.wash.strength = 0.0 if float(self.wash.strength) else 0.45
        self.triggerRedraw(1)

    # -- the developer overlay --------------------------------------------
    def debugRows(self):
        """A section of the demo's own numbers, beside the engine's.

        A provider returns whatever it has -- floats, flags, strings -- and
        the overlay formats them; it never returns a rendered line.
        """
        return [
            ('elapsed', systemtime.systemTime() - self.started),
            ('health', float(self.health.value)),
            ('spread', float(self.crosshair.spread)),
            ('messages', len(self.messages.messages)),
            ('damage marks', len(self.damage.marks)),
            ('washed', bool(float(self.wash.strength))),
        ]


if __name__ == "__main__":
    TestContext.ContextMainLoop()
