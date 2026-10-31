#! /usr/bin/env python
'''=A crowd of rigged figures, each doing its own thing=

[crowd_demo.py-screen-0001.png Screenshot]

150 copies of one rigged glTF model cross a field. Each one walks, breaks into
a run, stops, looks about, turns and sets off again, on its own schedule. A
single `OpenGLContext.character.crowd.Crowd` poses all of them in one pass over
arrays with a figure axis, and the renderer draws them in one instanced call.

The page follows the order the program runs in: the constants that describe
the model and the field, the context that builds the scene, the load that
fills it, and the step that runs once a frame. The model is `Fox` from the
Khronos sample catalogue (CC-BY 4.0, by PixelMannen and tomkranis), fetched
once into the on-disk asset cache.
:doc:`A character runs across a landscape </tutorials/character/character_run>`
covers a single character and its clip map.

Keys:
    s       turn the distance scheduler off and on
    b       cap the crowd at 80 poses a frame
    c       print the counts now
'''
'''_The renderer_

The script runs on the GLFW backend and selects the PBR pass. The skinning
shader belongs to that pass, and only figures the shader skins keep their
rest-pose vertices on the card. Identical vertices are what let 150 bodies
collapse into one instanced draw.'''
import os
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

import numpy as np

from OpenGLContext.character.locomotion import ClipMap
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.character.wander import STAND, TURN, WanderingCrowd
from OpenGLContext.loaders.gltf import load_gltf, parse_gltf, sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Background, Box, DirectionalLight, Material, Shape, Transform,
    sceneGraph,
)
from OpenGLContext.context import Context as BaseContext

'''_The model and the field_

`Fox` has 26 joints and three clips: `Survey` (a look around), `Walk` and
`Run`. It is authored 150 units long, so `SCALE` draws it 1.2 m from nose to
tail.

`FIELD` is the ground the figures keep to, as ``(x0, x1, z0, z1)`` in metres.
Its near edge is a few metres in front of the opening camera, so the nearest
bodies are in view whole.'''
MODEL = 'Fox'
FIGURES = 150
FIELD = (-13.0, 13.0, -19.0, -0.5)
SCALE = 0.008

'''_Clips and speed_

Each figure plays all three clips at once, in three layers: the idle at the
bottom, the walk and the run over it. What a figure shows is its own weights on
the layers. At half speed it is a blend of the idle and the walk, picking up
speed it is a blend of the walk and the run, and stopped it is the idle alone.

The crowd scales each clip's clock by how fast the body is travelling, so the
feet stay on the ground at any pace. That needs the clip's stride, the distance
one second of the clip at speed 1 carries a body. The stride is measured from
the model: the vertices in contact with the ground travel backwards under the
body at 102.7 model units a second in the walk and 171.9 in the run. Scaled by
`SCALE` these are metres a second. The strides also fix the speed at which
walking gives way to running. The same measurement shows the model faces +Z, so
no `facing` correction is passed to the crowd.'''
WALK_STRIDE = 102.7 * SCALE
RUN_STRIDE = 171.9 * SCALE

'''A `ClipMap` names the clip for each role together with its stride. A single
character's locomotion reads the same record, and the crowd takes it as
``clips=``. ``fade`` is the seconds a role takes to fade in.'''
CLIPS = ClipMap(idle='Survey', walk=('Walk', WALK_STRIDE), run=('Run', RUN_STRIDE),
                fade=0.35)

'''Each figure's travelling speed is drawn from this range, in metres a second.
It spans both strides, so the field holds walkers, runners and bodies part way
between the two.'''
SPEED = (0.55, 1.65)

'''_Which figures to pose_

Posing is the cost of a crowd, and a figure far from the eye does not need a
new pose every frame. `BANDS` lists distances from the eye in metres, each with
the poses a second a figure inside it asks for, where 0 means every frame. A
figure within 8 m is posed every frame, one within 20 m asks for 12 poses a
second, and anything further asks for 4. The clocks run either way, so a figure
that skipped a frame is where its clips say it is when its turn comes.

`EVERY_FRAME` is the same table with the scheduler off. `BUDGET` caps the
figures posed in one frame whatever the rates ask for, taking the figures in
turn so that none is starved.'''
BANDS = ((8.0, 0.0), (20.0, 12.0), (float('inf'), 4.0))
EVERY_FRAME = ((float('inf'), 0.0),)
BUDGET = 80

#: Frames between the printed counts.
REPORT_FRAMES = 60


'''_The context_

The eye starts 0.75 m above the ground. The fox stands 0.63 m high, and an eye
at head height would look down on the field from far above it. The orientation
pitches the view down by 0.12 radians about x.'''


class TestContext(BaseContext):
    """One crowd of one build, wandering, posed together and drawn instanced."""

    initialPosition = (0, 0.75, 2.6)
    initialOrientation = (1, 0, 0, -0.12)

    '''_The scene_

    ``OnInit`` builds the scene and starts the load. The ground is a 60 m
    slab. It receives shadows and casts none: there is nothing under it to
    shadow, and leaving it out of the shadow cascades leaves their depth passes
    to the bodies.'''
    def OnInit(self):
        BaseContext.OnInit(self)
        ground = Shape(appearance=Appearance(
                           material=Material(diffuseColor=(0.34, 0.36, 0.33))),
                       geometry=Box(size=(60.0, 0.1, 60.0)))
        ground.castShadow = False
        '''A `WanderingCrowd` is three parts tied together. A `Wander` keeps
        where each figure is, which way it faces and what it is doing, as
        arrays with one row per figure. A `Gait` per figure turns its speed
        into weights on the clips. A `Crowd` poses every figure from those
        weights.

        The arguments are the field, the range of speeds, the scale of each
        figure's `Transform` and the clip map. The wander draws its decisions
        from the session's entropy stream, so ``OPENGLCONTEXT_SEED=4242 python
        crowd_demo.py`` runs the same field every time.'''
        self.crowd = WanderingCrowd(FIELD, speed=SPEED, scale=SCALE, clips=CLIPS)
        '''The key light is a low sun over the viewer's shoulder, which puts a
        body's shadow clear of its own feet. The cool fill from the opposite
        side lights the flank the sun misses. The ground's `Transform` puts the top face of
        the slab at y = 0.'''
        children = [
            Background(skyColor=[(0.30, 0.45, 0.72), (0.63, 0.75, 0.90),
                                 (0.84, 0.86, 0.86)],
                       skyAngle=[1.15, 1.5708]),
            DirectionalLight(direction=(-0.42, -0.52, -0.74), intensity=1.4),
            DirectionalLight(direction=(0.6, -0.25, 0.75), intensity=0.45,
                             color=(0.6, 0.7, 1.0)),
            Transform(translation=(0.0, -0.05, -6.0), children=[ground]),
        ]
        self.sg = sceneGraph(children=children)
        '''Parsing the glTF is the slow part, so it runs on the scene loader's
        worker thread. `submit` takes a function that does not touch GL, and
        calls ``OnParsed`` on the render thread with the result when it
        returns. The window opens and draws the empty field meanwhile.

        There is one parse. Every figure is built from the parsed document and
        shares its vertex and keyframe data, which a crowd requires, since a
        joint has to mean the same joint in every figure.'''
        self.sceneLoader.submit(
            lambda: parse_gltf(fetch_to_cache(sample_model_url(MODEL))),
            label=MODEL, on_loaded=self.OnParsed)
        '''PBR ambient light comes from an environment probe, and this scene
        has none. ``gltf_scene_ambient`` supplies a flat fill of 0.25 and the
        directional lights do the rest.'''
        self.gltf_scene_ambient = 0.25
        '''The three keys are described with their handlers below.
        ``scheduling`` and ``budgeting`` are the two switches they set.'''
        self.addEventHandler('keypress', name='s', function=self.OnScheduler)
        self.addEventHandler('keypress', name='b', function=self.OnBudget)
        self.addEventHandler('keypress', name='c', function=self.OnCounts)
        self.scheduling = True
        self.budgeting = False
        #: Poses counted in each frame since the last printed report.
        self._posed = []
        print(__doc__)

    '''_Loading the model_

    ``OnParsed`` runs on the render thread when the worker has finished, and
    ``request.result`` is the parsed document. `load_gltf` builds a scenegraph
    from it without parsing again, and `CharacterModel` gives that scenegraph a
    rig and a mixer. ``crowd.add`` takes the model in and returns the
    `Transform` that places it, which goes into the scene.

    ``self.animate(self.step)`` has the context call ``step(dt)`` once a frame
    on the engine clock, before the frame is drawn, and keep drawing while it
    runs.'''
    def OnParsed(self, request):
        document = request.result
        figures = [self.crowd.add(CharacterModel(load_gltf(document=document)))
                   for _ in range(FIGURES)]
        self.sg.children = list(self.sg.children) + figures
        self.animate(self.step)

    '''_One frame_

    ``schedule`` sets each figure's pose rate from its distance to the eye,
    which is the platform's position. ``update`` moves every figure by ``dt``
    seconds, then poses the ones that are due and returns how many that was.
    The count goes into ``_posed`` for the report.

    ``mode=self`` gives the crowd the context. Where the driver has compute
    shaders, the crowd then composes the skeletons on the card.'''
    def step(self, dt):
        self.crowd.schedule(self.platform.position,
                            BANDS if self.scheduling else EVERY_FRAME)
        self._posed.append(self.crowd.update(
            dt, budget=BUDGET if self.budgeting else None, mode=self))
        if len(self._posed) >= REPORT_FRAMES:
            self._report()

    '''_The keys_

    `s` swaps the distance bands for `EVERY_FRAME`, and `b` applies `BUDGET`
    on top of whichever table is in use. `c` prints the counts without waiting
    for the next report. With the scheduler off every figure is posed every
    frame, so the report reads 150.0: the same picture for nearly three times
    the posing. Walking into the field brings the figures around the eye into
    the 8 m band, and their count rises with it.

    Each handler calls ``triggerRedraw(1)``, which starts a redraw at once if
    the context is not already drawing.'''
    def OnScheduler(self, event):
        self.scheduling = not self.scheduling
        self.triggerRedraw(1)

    def OnBudget(self, event):
        self.budgeting = not self.budgeting
        self.triggerRedraw(1)

    def OnCounts(self, event=None):
        self._report()

    '''_The report_

    Every 60 frames the demo prints what the frame came to:
        150 figures  scheduler ON  posed 44.7 of 150 per frame, in 4 runs
            61 walking, 47 running, 11 turning, 31 standing
            112 shapes -> 2 draws (111 instanced in 1 group)

    * posed - the figures brought up to date, averaged over the frames since
      the last report. A figure not posed holds the pose it has.
    * runs - the sets of arithmetic those poses took. Figures doing the same
      kind of thing are answered together, so a field of standing, walking,
      running and part-way figures costs one run for each kind rather than one
      for each body.
    * shapes and draws - what the render pass made of the bodies. Every body
      holds the same rest-pose vertices, so they collapse into one instanced
      draw in which each instance names its own range of the joint palette.
      The second draw is the ground. The shadow pass batches the same way and
      reads the same palette, so a shadow is of the pose its body is in.

    The scene holds 151 shapes, 150 bodies and the ground. The shape count is
    those that survive frustum culling.

    The walking and running counts come from the `Wander` arrays. A figure
    that is neither standing nor turning is running when its speed passes the
    run stride and walking otherwise.'''
    def _report(self):
        stats = getattr(self, 'renderStats', None)
        if stats is None or not self._posed:
            return
        mean = sum(self._posed) / float(len(self._posed))
        self._posed = []
        wander = self.crowd.wander
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


if __name__ == "__main__":
    TestContext.ContextMainLoop()
