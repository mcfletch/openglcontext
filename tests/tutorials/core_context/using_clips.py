#! /usr/bin/env python
'''=Playing a canned animation=

[using_clips.py-screen-0001.png Screenshot]

In :doc:`loading_gltf_model` we reached into a
glTF model and crudely animated the swinging of a lamp based on math.
However, this isn't a particularly useful way to get smooth and natural
animations.

glTF models can contain an authored animation created by the modeller.
These animations are normally given a name such as "walk" or "run".
OpenGLContext can play the clips to allow for animating a character in
the world (player or NPC).

You'll see references to "rigged" models, this is basically a model that is
ready to be animated, with joints set up so that the mesh can be deformed by
the movement of the joints. If your models use a common joint layout then
they can often share animations with other models.

We'll be using the `Fox` model (CC-BY 4.0, by PixelMannen and tomkranis)
which has 3 animations:

* "survey" (idle animation that looks around)
* "walk" (slow padding around)
* "run" (jumping run)

Keys:
    1 2 3   play that clip
    space   blend into the next one
'''
import os

from OpenGLContext.context import Context as BaseContext
''':py:class:`CharacterModel` packages up the information for an animated
character in OpenGLContext. It lets you introspect the animations, joints,
and attachment points (think hands) from the model.
'''
from OpenGLContext.character.model import CharacterModel
'''As with :doc:`loading_gltf_model` we are going to use
a Kronos sample glTF for this demo, so we'll use the sample index's function
to get the current URL for it.'''
from OpenGLContext.loaders.gltf import sample_model_url
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)

'''Define which model we are going to use, and which clips inside it.'''
MODEL = 'Fox'
#: The names this model's clips were authored under.  ``model.clips`` is where
#: they come from for a file whose names you do not already know.
CLIPS = ['Survey', 'Walk', 'Run']


class TestContext(BaseContext):
    initialPosition = (30, 32, 165)
    initialOrientation = (-1, 0, 0, 0.02)
    model:'CharacterModel|None' = None
    index: int = 0

    def OnInit(self):
        """Setup the context for rendering"""
        '''We'll create a generic empty scene for the character to wander around.'''
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.16, 0.18, 0.21)]),
            DirectionalLight(direction=(-0.4, -0.7, -0.5)),
        ])
        '''Our character is in a glTF file, so we need to get it loaded before
        we can start working with it.'''
        self.sceneLoader.load(sample_model_url(MODEL), on_loaded=self.OnLoaded)
        '''Setup our demo controls so that numbers trigger one of the three
        animations in the file.'''
        for key in ('1', '2', '3'):
            self.addEventHandler('keypress', name=key, function=self.OnChoose)
        '''The let a space run the "next" animation.'''
        self.addEventHandler('keypress', name=' ', function=self.OnNext)
        print(__doc__)

    def OnLoaded(self, request):
        """Process the loaded character"""
        '''CharacterModel can parse a loaded glTF scene, which is normally
        what you want to do after you load the character.'''
        self.model = CharacterModel.from_scene(request.result)
        print('%s carries %d clips: %s' % (
            MODEL, len(self.model.clips), ', '.join(sorted(self.model.clips)),
        ))
        '''We'll start the "idle" animation as soon as the character loads,
        for the Fox this is a head turn left and right. The `loop` option
        repeats the animation after it finishes.'''
        self.model.play(CLIPS[self.index], loop=True)
        '''All that's left is to add the Character's graphical representation
        to the scenegraph. `CharacterModel` has a `group` member which is 
        where the geometry is made available.'''
        self.sg.children = list(self.sg.children) + [
            Transform(rotation=(0, 1, 0, 0.7), children=[self.model.group])]
        '''In order to get updates when the scene's time has advanced, we
        call self.animate on the `CharacterModel` which registers the model
        to receive time events from this `Context`.'''
        self.animating = self.animate(self.model)

    def OnChoose(self, event):
        """Update the currently playing animation."""
        '''The event is a key-press with values 1,2 or 3, which we convert
        into an integer and then to 0-indexed values to match python form.'''
        self.index = int(event.name) - 1
        self.play()

    def OnNext(self, event):
        """Select the next index (rotating to start at end)"""
        self.index = (self.index + 1) % len(CLIPS)
        self.play()

    def play(self):
        """Trigger the currently selected (self.index) animation to play"""
        '''If we haven't loaded the model yet, we can't play yet.'''
        if self.model is None:
            return
        name = CLIPS[self.index]
        '''We want to start the current animation, but fade out the old
        animation so that there isn't a sudden jerky jump between the two.
        We give the fade argument 1/4 second here to fade out the old 
        animation.'''
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
    TestContext.ContextMainLoop(definition={
        "renderer":"pbr",
    })
