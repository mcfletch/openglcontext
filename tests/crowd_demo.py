#! /usr/bin/env python
'''=A crowd of rigged figures (posed together, drawn instanced)=

[crowd_demo.py-screen-0001.png Screenshot]

A hundred and fifty copies of one rigged glTF model, walking.  Each figure is
a scenegraph of its own built from **one** parsed document, each is at a
different point in its stride, and all of them are posed by a single
`OpenGLContext.character.crowd.Crowd` -- one pass over arrays with a figure
axis on them, rather than a hundred and fifty passes over one figure each.

Every sixty frames the demo prints what the frame came to:

    150 figures  scheduler ON  posed 52.3 of 150 per frame
        107 shapes -> 2 draws (106 instanced in 1 group)

 * *posed* -- the figures the crowd brought up to date, averaged over the
   frames since the last line.  A figure that is not posed holds the pose it
   has; the clocks run either way, so it is where its clip says it is when its
   turn comes.
 * *shapes / draws* -- what the render pass made of the bodies.  The shader
   skins them, so every one of them holds the same rest-pose vertices and they
   collapse into a single instanced draw, each instance naming its own range of
   the joint palette; the second draw is the ground.  The scene is 151 shapes
   -- a hundred and fifty bodies and the ground -- and 107 of them survive
   frustum culling at the opening camera.

Press `s` to turn the distance scheduler off and on.  On, a figure within
eight metres of the eye is posed every frame, one within twenty asks for
twelve poses a second, and anything further asks for four.  Off, every figure
is posed every frame and the count reads 150.0 -- the same picture, for
nearly three times the posing.

Press `b` to cap the crowd at eighty figures a frame on top of the rates,
which from the opening camera brings the mean to 38.4; `c` prints the counts
on demand.  The usual keys walk around, and the count follows the eye: walk
into the back rows and the figures there start asking to be posed every frame.

The model is `CesiumMan` from the Khronos sample catalogue -- twenty-two
joints and one two-second clip -- fetched once into the on-disk asset cache.
'''
import math
import os

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
# The shader that skins a figure on the card is the PBR pass's, and only
# figures the shader skins hold their rest-pose vertices -- which is what lets
# a hundred and fifty of them collapse into one instanced draw.
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
from OpenGLContext.character.crowd import Crowd
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.loaders.gltf import load_gltf, parse_gltf, sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)

BaseContext = testingcontext.getInteractive('glfw')

#: Khronos sample model to fill the field with: a walking figure, twenty-two
#: joints and one clip.
MODEL = 'CesiumMan'

#: Figures across and back, and the metres between them.  Enough of them that
#: one draw against one per body is an obvious difference.
COLUMNS, ROWS = 15, 10
SPACING = (1.25, 1.6)

#: Seconds of the clip between one figure and the next, so no two are at the
#: same point in their stride.  Prime-ish against the clip's two seconds, so
#: the phases spread rather than repeating down each row.
PHASE_STEP = 0.131

#: Where the distance bands fall, in metres from the eye, and the poses a
#: second a figure in each asks for.  0 means every frame.
NEAR, FAR = 8.0, 20.0
NEAR_RATE, MID_RATE, FAR_RATE = 0.0, 12.0, 4.0

#: Figures the `b` key caps a frame at, whatever the rates ask for.
BUDGET = 80

#: The animation step.  A fixed step rather than the wall clock, so a capture
#: of this demo lands on the same poses every time.
FRAME_STEP = 1 / 60.0

#: Frames between print-outs.
REPORT_FRAMES = 60


class TestContext(BaseContext):
    """One crowd of one build, posed together and drawn instanced."""

    initialPosition = (0, 2.0, 3.6)
    initialOrientation = (1, 0, 0, -0.20)

    def OnInit(self):
        BaseContext.OnInit(self)
        # One parse, one scenegraph per figure: they share their vertex and
        # keyframe data, and a crowd requires them to be of one build anyway.
        document = parse_gltf(fetch_to_cache(sample_model_url(MODEL)))
        # The ground takes shadows but casts none: there is nothing under it
        # to shadow, and keeping a slab this wide out of every cascade leaves
        # the depth passes to the bodies.
        ground = Shape(appearance=Appearance(
                           material=Material(diffuseColor=(0.30, 0.32, 0.36))),
                       geometry=Box(size=(48.0, 0.1, 48.0)))
        ground.castsShadow = False
        self.crowd = Crowd()
        #: (member, x, z) for each figure, which is what the scheduler reads.
        self.placed = []
        children = [
            Background(skyColor=[(0.30, 0.45, 0.72), (0.63, 0.75, 0.90),
                                 (0.84, 0.86, 0.86)],
                       skyAngle=[1.15, 1.5708]),
            # A key light over the viewer's shoulder and a cool fill from the
            # far side, so a body reads as a body rather than a silhouette.
            DirectionalLight(direction=(-0.30, -0.90, -0.32), intensity=1.4),
            DirectionalLight(direction=(0.6, -0.25, 0.75), intensity=0.45,
                             color=(0.6, 0.7, 1.0)),
            Transform(translation=(0.0, -0.05, -4.0), children=[ground]),
        ]
        clip = None
        for index in range(COLUMNS * ROWS):
            model = CharacterModel(load_gltf(document=document))
            if clip is None:
                clip = sorted(model.clips)[0]
            model.play(clip)
            # Each figure a different distance into its stride.  The clock is
            # the track's own, so nothing about the crowd has to know.
            track = model.mixer.layers[0].tracks[0]
            track.time = (index * PHASE_STEP) % model.clips[clip].duration
            x, z = self._place(index)
            children.append(Transform(
                translation=(x, 0.0, z),
                # Facing the viewer, a little off square, so the field reads
                # as a crowd rather than as a parade.
                rotation=(0, 1, 0, math.pi + 0.25 * math.sin(index * 2.1)),
                children=[model.group]))
            self.placed.append((self.crowd.add(model), x, z))
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

    @staticmethod
    def _place(index):
        """Where one figure stands: a grid, with alternate rows offset."""
        column, row = index % COLUMNS, index // COLUMNS
        x = (column - (COLUMNS - 1) / 2.0) * SPACING[0]
        return x + (SPACING[0] / 2.0 if row % 2 else 0.0), -row * SPACING[1]

    def _schedule(self):
        """Ask for fewer poses a second the further a figure is from the eye."""
        eye = self.platform.position
        for member, x, z in self.placed:
            if not self.scheduling:
                member.rate = 0.0
                continue
            distance = math.hypot(x - eye[0], z - eye[2])
            member.rate = (NEAR_RATE if distance < NEAR else
                           MID_RATE if distance < FAR else FAR_RATE)

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
        print('%d figures  scheduler %s%s  posed %.1f of %d per frame\n'
              '    %d shapes -> %d draws (%d instanced in %d group%s)'
              % (len(self.crowd), 'ON' if self.scheduling else 'OFF',
                 ', budget %d' % BUDGET if self.budgeting else '',
                 mean, len(self.crowd), stats.shapes, stats.draws,
                 stats.instances, stats.instanceGroups,
                 '' if stats.instanceGroups == 1 else 's'))

    def OnDraw(self, *args, **named):
        self._schedule()
        # The whole crowd in one call, in place of a model.update() each.
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
