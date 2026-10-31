#! /usr/bin/env python
'''=Adding Nodes at Runtime=

A scene is a tree of nodes, and the tree can be changed while the world is
running. This tutorial adds a teapot to a group every tenth of a second, and
adds another each time the `a` key is pressed. Past 128 teapots it empties the
group and starts again.

Every teapot shares one `Teapot` geometry node and has a `Material` of its own.
The PBR render pass collapses shapes that share geometry into a single
instanced draw, each instance reading its colour from the group's material
array, so the cost of a frame stays close to flat as the count climbs instead
of growing with one draw call per teapot.
'''
import random

from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.viewer import ViewerContext as BaseContext

'''The scene starts with a group holding one teapot. The `DEF` name is how
a scene loaded from a file would name the group; here the context reaches it
through `children[0]`.'''
scene = sceneGraph(
    children = [
        Group(
            DEF = 'g',
            children = [
                Shape(
                    geometry = Teapot( size=.2),
                )
            ],
        ),
    ],
)
'''`ViewerContext` is a `Context` with the viewer's navigation. The
handlers are registered in `OnInit`: the `a` key adds a teapot, and a repeating
`Timer` calls the same handler every 0.1 seconds.'''
class TestContext( BaseContext ):
    def OnInit( self ):
        self.sg = scene
        self.addEventHandler( "keypress", name="a", function = self.OnAdd)
        self.time = Timer( duration = .1, repeating = 1 )
        self.time.addEventHandler( "cycle", self.OnAdd )
        self.time.register (self)
        self.time.start ()
        self.teapot = Teapot( size=.2)
        
    def OnAdd( self, _event ):
        '''Each call appends a `Transform` holding a `Shape` at a random
        position, sharing `self.teapot` and with a random colour. Appending to
        the `children` list is all the scene needs to be told.'''
        children = self.sg.children[0].children
        if len(children) > 128:
            children[:] = []
        else:
            cube = 10
            position = ( 
                (random.random()-.5)*cube,
                (random.random()-.5)*cube,
                (random.random()-.5)*cube 
            )
            color = (random.random(),random.random(),random.random())
            children.append( Transform(
                translation = position,
                children = [
                    Shape(
                        geometry = self.teapot,
                        appearance = Appearance(
                            material=Material( 
                                diffuseColor = color,
                            )
                        ),
                    ),
                ],
            ))

if __name__ == "__main__":
    TestContext.ContextMainLoop(definition={
        'renderer':'pbr',
        'fullscreen': True,
    })
