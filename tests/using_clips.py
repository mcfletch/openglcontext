#! /usr/bin/env python
'''=Playing a canned animation=

[using_clips.py-screen-0001.png Screenshot]

A rigged model plays the clips its file was authored with.  The model is
`Fox` from the Khronos sample catalogue (CC-BY 4.0, by PixelMannen and
tomkranis), which carries three: a survey, a walk and a run.

Keys:
    1 2 3   play that clip
    space   blend into the next one
'''
import os
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
'''``CharacterModel`` is a rigged model and what can be done with it: the
clips it carries, the skeleton they move, and the points something can be
hung on.'''
from OpenGLContext.events.systemtime import systemTime
from OpenGLContext.character.model import CharacterModel
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)

MODEL = 'Fox'
#: The names this model's clips were authored under.  ``model.clips`` is where
#: they come from for a file whose names you do not already know.
CLIPS = ['Survey', 'Walk', 'Run']


class TestContext(BaseContext):
    initialPosition = (30, 32, 165)
    initialOrientation = (-1, 0, 0, 0.02)

    def OnInit(self):
        '''Loading a character is loading a glTF file: ``CharacterModel.load``
        takes a path, a URL or the bytes of a ``.glb``.'''
        self.model = CharacterModel.load(fetch_to_cache(sample_model_url(MODEL)))
        print('%s carries %d clips: %s' % (
            MODEL, len(self.model.clips), ', '.join(sorted(self.model.clips)),
        ))
        '''``play`` starts a clip.  ``loop`` keeps it going, and ``fade`` is
        how many seconds to take blending out of whatever was playing, so a
        walk becomes a run over a quarter of a second rather than switching
        between poses in one frame.'''
        self.index = 0
        self.model.play(CLIPS[self.index], loop=True)
        '''``model.group`` is the renderable subtree, mounted in the scene
        like any other node.'''
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.16, 0.18, 0.21)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.5)),
            Transform(rotation=(0, 1, 0, 0.7), children=[self.model.group]),
        ])
        for key in ('1', '2', '3'):
            self.addEventHandler('keypress', name=key, function=self.OnChoose)
        self.addEventHandler('keypress', name=' ', function=self.OnNext)
        self.last = systemTime()
        print(__doc__)

    def OnIdle(self, event=None):
        '''The clips advance when they are told how much time has passed.
        ``update`` steps every layer and poses the skeleton; nothing moves
        without it, and a paused game is a game that stops calling it.'''
        now = systemTime()
        self.model.update(now - self.last)
        self.last = now
        '''A posed figure is a changed scene, so the frame has to be drawn
        again.'''
        self.triggerRedraw(1)

    def OnChoose(self, event):
        self.index = int(event.name) - 1
        self.play()

    def OnNext(self, event):
        self.index = (self.index + 1) % len(CLIPS)
        self.play()

    def play(self):
        '''Playing a second clip on the same layer replaces the first.  Two
        clips at once -- a walk on the legs and a wave on the arm -- are two
        *layers*, which is what :doc:`the characters page </characters>`
        covers.'''
        name = CLIPS[self.index]
        self.model.play(name, loop=True, fade=0.25)
        print('playing %s' % (name,))


'''_Where the clips come from_

A clip is an animation in the glTF file, and the file is usually Blender's
output.  Blender's own material on animating a rigged figure is the
*Animation & Rigging* half of its manual --
[https://docs.blender.org/manual/en/latest/animation/index.html Animation &
Rigging] for the editors and the workflow,
[https://docs.blender.org/manual/en/latest/animation/armatures/index.html
Armatures] for the skeleton that the mesh is bound to, and
[https://studio.blender.org/training/animation-fundamentals/ Animation
Fundamentals] on Blender Studio for a course that works up from a bouncing
ball to character acting.

The names are the track names - an action in Blender has a name, but what
the exporter writes as the glTF animation's name comes from the NLA track
it is pushed onto: in the Dope Sheet's Action Editor, name the action, then
*Push Down* to make a strip of it, and name the *NLA track* in the
Nonlinear Animation editor -- that name is the one ``model.clips`` answers
with and the one ``play()`` is called with.  A figure with a Walk, a Run
and an Idle is three tracks, each holding one strip.

Exporting them - *File > Export > glTF 2.0*, then *Animation > NLA
Strips* on -- with it off, only the object's active action is written, and
the three clips arrive as one.  The merge mode beside it decides whether
tracks of the same name across several objects become one animation or
several; one track per clip and the default is what a character wants.
*Animation > Always Sample Animations* is worth leaving on for a rig
whose bones are driven by constraints, since the constraint itself does not
export -- the samples of what it produced do.

What arrives - each glTF animation becomes one entry in ``model.clips``,
keyed by its name.  A file whose names you do not know prints them::

    print(sorted(CharacterModel.load('mymodel.glb').clips))
'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()
