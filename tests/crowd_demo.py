#! /usr/bin/env python
'''=A crowd of rigged figures, each doing its own thing=

[crowd_demo.py-screen-0001.png Screenshot]

A hundred and fifty copies of one rigged glTF model, each crossing the field on
its own: walking, breaking into a run, coming to a halt, looking about, turning
towards somewhere else and setting off again.  Every figure is a scenegraph of
its own built from **one** parsed document, no two are at the same point in the
same thing, and all of them are posed by a single
`OpenGLContext.character.crowd.Crowd` -- one pass over arrays with a figure
axis on them, rather than a hundred and fifty passes over one figure each.

Where they go comes out of `OpenGLContext.character.wander`, and out of the
session seed, so `OPENGLCONTEXT_SEED=4242 python crowd_demo.py` runs the same
field every time.

**Every body is part way through a blend of its own.**  The model's three clips
sit in three layers -- the idle underneath, the walk and the run over it -- and
what a figure shows is its own weights on them: a body at half speed is a
blend of the idle and the walk, one picking up speed is a blend of the walk and
the run, and one that has stopped is the idle alone.  The clips' clocks are
scaled by how fast each body is actually travelling, so the feet stay on the
ground at any pace.

Every sixty frames the demo prints what the frame came to:

    150 figures  scheduler ON  posed 44.7 of 150 per frame, in 4 runs
        61 walking, 47 running, 11 turning, 31 standing
        112 shapes -> 2 draws (111 instanced in 1 group)

 * *posed* -- the figures the crowd brought up to date, averaged over the
   frames since the last line.  A figure that is not posed holds the pose it
   has; the clocks run either way, so it is where its clips say it is when its
   turn comes.
 * *runs* -- how many sets of arithmetic those poses took.  Figures doing the
   same kind of thing are answered together, so a field where some are
   standing, some walking, some running and some part way between costs one run
   for each kind and not one for each body.
 * *shapes / draws* -- what the render pass made of the bodies.  The shader
   skins them, so every one of them holds the same rest-pose vertices and they
   collapse into a single instanced draw, each instance naming its own range of
   the joint palette; the second draw is the ground.  The shadow pass batches
   the same way and reads the same palette, so a body's shadow is of the pose
   it is in.  The scene is 151 shapes -- a hundred and fifty bodies and the
   ground -- and the count is those of them that survive frustum culling.

Press `s` to turn the distance scheduler off and on.  On, a figure within eight
metres of the eye is posed every frame, one within twenty asks for twelve poses
a second, and anything further asks for four.  Off, every figure is posed every
frame and the count reads 150.0 -- the same picture, for nearly three times the
posing.

Press `b` to cap the crowd at eighty figures a frame on top of the rates; `c`
prints the counts on demand.  The usual keys walk around, and the count follows
the eye: walk into the field and the figures around you start asking to be
posed every frame.

The model is `Fox` from the Khronos sample catalogue -- twenty-six joints and
three clips -- fetched once into the on-disk asset cache.
'''
import os
from functools import partial

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
# The shader that skins a figure on the card is the PBR pass's, and only
# figures the shader skins hold their rest-pose vertices -- which is what lets
# a hundred and fifty of them collapse into one instanced draw.
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

import numpy as np

from OpenGLContext import testingcontext
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.character.wander import STAND, TURN, Gait, WanderingCrowd
from OpenGLContext.loaders.gltf import load_gltf, parse_gltf, sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

BaseContext = testingcontext.getInteractive('glfw')

#: Khronos sample model to fill the field with: a fox, twenty-six joints, and
#: the three clips a wandering figure wants -- a look-around, a walk and a run.
MODEL = 'Fox'
IDLE, WALK, RUN = 'Survey', 'Walk', 'Run'

#: Figures in the field.  Enough of them that one draw against one per body is
#: an obvious difference.
FIGURES = 150

#: The ground they keep to, as ``(x0, x1, z0, z1)`` in metres.  Wide enough
#: that a hundred and fifty of them are a crowd rather than a queue, and its
#: near edge a few metres in front of the opening camera, so the nearest bodies
#: are close enough to read whole rather than walking past the lens.
FIELD = (-13.0, 13.0, -19.0, -0.5)

#: The model is authored a hundred and fifty units long, so it is drawn at this
#: to be a metre and a quarter nose to tail.
SCALE = 0.008

#: Metres each locomotion clip carries a figure in a second when it is played
#: at speed 1.  Measured as how fast the vertices in contact with the ground
#: travel backwards under the body -- 102.7 and 171.9 model units a second,
#: scaled by `SCALE`.  They settle both how fast to run each clip for a given
#: speed and where the crossover from walking to running falls, and the same
#: measurement says the model faces +Z, so no `facing` correction is wanted.
WALK_STRIDE = 102.7 * SCALE
RUN_STRIDE = 171.9 * SCALE

#: How fast a figure travels, in metres a second, drawn per figure.  Spans the
#: two strides above, so the field holds walkers, runners and bodies mid-blend
#: between the two.
SPEED = (0.55, 1.65)

#: Where the distance bands fall, in metres from the eye, and the poses a
#: second a figure in each asks for.  0 means every frame.
BANDS = ((8.0, 0.0), (20.0, 12.0), (float('inf'), 4.0))

#: What the bands come to with the scheduler off: everyone, every frame.
EVERY_FRAME = ((float('inf'), 0.0),)

#: Figures the `b` key caps a frame at, whatever the rates ask for.
BUDGET = 80

#: The animation step.  A fixed step rather than the wall clock, so a capture
#: of this demo lands on the same poses every time.
FRAME_STEP = 1 / 60.0

#: Frames between print-outs.
REPORT_FRAMES = 60


class TestContext(BaseContext):
    """One crowd of one build, wandering, posed together and drawn instanced."""

    # Low, because the figures are knee-high: an eye at head height looks down
    # on a field of them and they read as models on a table.
    initialPosition = (0, 0.75, 2.6)
    initialOrientation = (1, 0, 0, -0.12)

    def OnInit(self):
        BaseContext.OnInit(self)
        # One parse, one scenegraph per figure: they share their vertex and
        # keyframe data, and a crowd requires them to be of one build anyway.
        document = parse_gltf(fetch_to_cache(sample_model_url(MODEL)))
        # The ground takes shadows but casts none: there is nothing under it
        # to shadow, and keeping a slab this wide out of every cascade leaves
        # the depth passes to the bodies.
        ground = Shape(appearance=Appearance(
                           material=Material(diffuseColor=(0.34, 0.36, 0.33))),
                       geometry=Box(size=(60.0, 0.1, 60.0)))
        ground.castsShadow = False
        self.crowd = WanderingCrowd(
            FIELD, speed=SPEED, scale=SCALE,
            gait=partial(Gait, walk=WALK, run=RUN, idle=IDLE,
                         walk_stride=WALK_STRIDE, run_stride=RUN_STRIDE))
        children = [
            Background(skyColor=[(0.30, 0.45, 0.72), (0.63, 0.75, 0.90),
                                 (0.84, 0.86, 0.86)],
                       skyAngle=[1.15, 1.5708]),
            # A key light over the viewer's shoulder, low enough that a body
            # this size throws a shadow clear of its own feet, and a cool fill
            # from the far side so it reads as a body rather than a silhouette.
            DirectionalLight(direction=(-0.42, -0.52, -0.74), intensity=1.4),
            DirectionalLight(direction=(0.6, -0.25, 0.75), intensity=0.45,
                             color=(0.6, 0.7, 1.0)),
            Transform(translation=(0.0, -0.05, -6.0), children=[ground]),
        ]
        for _ in range(FIGURES):
            children.append(self.crowd.add(CharacterModel(
                load_gltf(document=document))))
        self.sg = sceneGraph(children=children)
        # PBR ambient is image-based and this scene carries no probe, so the
        # fill is set here and the sun does the rest of the lighting.
        self.gltf_scene_ambient = 0.25
        self.addEventHandler('keypress', name='s', function=self.OnScheduler)
        self.addEventHandler('keypress', name='b', function=self.OnBudget)
        self.addEventHandler('keypress', name='c', function=self.OnCounts)
        #: Whether the distance bands are applied at all.
        self.scheduling = True
        #: Whether the per-frame cap is applied on top of them.
        self.budgeting = False
        #: Poses counted since the last print-out.
        self._posed = []
        print(__doc__)

    def OnScheduler(self, event):
        self.scheduling = not self.scheduling
        self.triggerRedraw(1)

    def OnBudget(self, event):
        self.budgeting = not self.budgeting
        self.triggerRedraw(1)

    def OnCounts(self, event=None):
        self._report()

    def _report(self):
        stats = getattr(self, 'renderStats', None)
        if stats is None or not self._posed:
            return
        mean = sum(self._posed) / float(len(self._posed))
        self._posed = []
        wander = self.crowd.wander
        # Which of the two locomotion clips is the larger share of a travelling
        # body, which is what the eye reads as walking or running.
        running = (wander.state > TURN) & (wander.speed > RUN_STRIDE)
        walking = (wander.state > TURN) & ~running
        print('%d figures  scheduler %s%s  posed %.1f of %d per frame, in'
              ' %d run%s\n    %d walking, %d running, %d turning, %d standing\n'
              '    %d shapes -> %d draws (%d instanced in %d group%s)'
              % (len(self.crowd), 'ON' if self.scheduling else 'OFF',
                 ', budget %d' % BUDGET if self.budgeting else '',
                 mean, len(self.crowd), self.crowd.crowd.groups,
                 '' if self.crowd.crowd.groups == 1 else 's',
                 int(np.count_nonzero(walking)),
                 int(np.count_nonzero(running)),
                 int(np.count_nonzero(wander.state == TURN)),
                 int(np.count_nonzero(wander.state == STAND)),
                 stats.shapes, stats.draws,
                 stats.instances, stats.instanceGroups,
                 '' if stats.instanceGroups == 1 else 's'))

    def OnDraw(self, *args, **named):
        self.crowd.schedule(self.platform.position,
                            BANDS if self.scheduling else EVERY_FRAME)
        # The whole crowd in one call: everybody moves, then everybody poses.
        # `mode` is what lets it compose the skeletons on the card.
        self._posed.append(self.crowd.update(
            FRAME_STEP, budget=BUDGET if self.budgeting else None, mode=self))
        drawn = super(TestContext, self).OnDraw(*args, **named)
        if len(self._posed) >= REPORT_FRAMES:
            self._report()
        return drawn

    def OnIdle(self, event=None):
        # The crowd is stepped from the draw, so a still frame is a stopped
        # walk: an animation demo has to keep asking for frames.
        self.triggerRedraw(1)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
