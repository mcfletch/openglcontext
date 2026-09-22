#! /usr/bin/env python
'''=Four views of a model=

[multiview_quad.py-screen-0001.png Screenshot]

A glTF model in the four views an editor opens on: the plan, the front
elevation and the view from the left, all orthographic, around a
perspective view that orbits it.  `QuadView` from the editor toolkit builds
the layout and moves each view's camera; the context draws the four views
as one frame, through one camera each.

Give it a path to draw a model of your own:

    python multiview_quad.py mymodel.glb

Without one it draws `Lantern` from the Khronos sample catalogue (CC0).

Mouse and keys:

    drag         pan an orthographic view, or orbit the perspective view
    right-drag   pan the perspective view
    wheel        zoom the view under the pointer
    space        give the active view the whole window, and give it back
    f            frame the model in every view again
    i            print how this driver is drawing the views
'''
'''A glTF model is drawn with the PBR renderer, chosen before the engine is
imported; :doc:`Loading a glTF model <using_gltf_model>` covers the loading
itself.'''
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
'''``QuadView`` is plain Python: views, cameras and the arithmetic of
panning and zooming them, with no GL in it.  The layout it builds is what the
context draws.'''
from OpenGLContext.edit.quadview import QuadView
from OpenGLContext.loaders.gltf import load_gltf, sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
from OpenGLContext.passes import renderpass
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)

MODEL = 'Lantern'


def model_path(arguments):
    '''The file named on the command line, or the sample model.'''
    for argument in arguments:
        if argument.lower().endswith(('.gltf', '.glb')) and os.path.exists(argument):
            return argument
    return fetch_to_cache(sample_model_url(MODEL))


class TestContext(BaseContext):
    def OnInit(self):
        scene = load_gltf(model_path(sys.argv[1:]))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.15, 0.17, 0.2)]),
            DirectionalLight(direction=(-0.4, -0.6, -1.0), intensity=1.0),
            scene.group,
        ])
        '''The model is left in its own units and where the file put it; the
        views are fitted to it instead.  ``minimum`` and ``maximum`` are the
        corners of the box around what was loaded.'''
        self.bounds = (scene.minimum, scene.maximum)

        '''*The four views.*  ``QuadView()`` makes a ``'top'``, a ``'front'``
        and a ``'left'`` view, each an ``OrthoViewPlatform`` clearing to a flat
        grey, and a ``'perspective'`` view, an ``OrbitViewPlatform`` that draws
        the scene's own background.  Assigning ``quad.layout`` to
        ``viewLayout`` is all it takes for the context to draw them.

        Framing fits each view to the size the layout gives it, so the layout
        is arranged for the window first.'''
        self.quad = QuadView()
        self.viewLayout = self.quad.layout
        self.quad.layout.arrange(*self.getViewPort())
        self.quad.frame(*self.bounds)

        self.addEventHandler('keypress', name=' ', function=self.OnMaximise)
        self.addEventHandler('keypress', name='f', function=self.OnFrame)
        self.addEventHandler('keypress', name='i', function=self.OnStrategy)
        print(__doc__)

    def ProcessEvent(self, event):
        '''*The pointer.*  Every event reaching the context is offered to the
        quad view first.  The context has already said which view the event
        belongs to -- the one under the pointer, or the one a held button
        began in -- and ``handle`` moves that view's camera.  An event it
        takes goes no further, so the context's own navigation never sees a
        drag meant for a view.'''
        if self.quad.handle(event):
            self.triggerRedraw(1)
            return None
        return super(TestContext, self).ProcessEvent(event)

    def hasMouseMoveHandlers(self):
        '''The drags are read in ``ProcessEvent``, which the handler registry
        does not see; saying so keeps the pointer's movements coming.'''
        return True

    def OnMaximise(self, event):
        '''``maximise`` gives the active view -- the last one clicked in --
        the whole window, and the same call gives it back.'''
        self.quad.layout.maximise()
        self.triggerRedraw(1)

    def OnFrame(self, event):
        self.quad.layout.arrange(*self.getViewPort())
        self.quad.frame(*self.bounds)
        self.triggerRedraw(1)

    def OnStrategy(self, event):
        '''*How the views are drawn.*  A driver with viewport arrays draws
        the opaque scene once for all four views, through a geometry stage
        (``geometry``) or by routing each copy from the vertex stage
        (``vertex``); any other draws the views in turn (``sequential``).
        The choice is made on the first frame, and a strategy whose programs
        do not compile gives way to the next.'''
        flat = renderpass.FLAT
        print('views drawn by: %s' % (getattr(flat, 'multiviewStrategy', None),))


if __name__ == "__main__":
    TestContext.ContextMainLoop()
