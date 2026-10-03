#! /usr/bin/env python
'''=Getting a Context for Rendering=

OpenGLContext is a large project, with lots of different knobs and dials
you can use to control your 3D world. We're going to start with the smallest
setup we can use to get a working 3D renderer.
'''
'''
OpenGLContext's core Context class provides the basic machinery needed for
most 3D worlds, including navigation, and geometry renderering. It defaults
to a modern Physically Based Renderer that requires a modern OpenGL 3.3+ 
driver. Most machines produced after about 2014 should be able to provide
this kind of context.
'''
from OpenGLContext.context import Context as BaseContext 
'''
These imports are so that we will have something to show on our 3D window.
'''
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph, Shape, Teapot, PBRMaterial,Appearance,
)

'''
If you are migrating from an older version of OpenGLContext, you will
likely want to replace your `BaseContext = testingcontext.testingContext()`
calls with the import above. We've folded most interactive features into the
base Context class.
'''
class TestContext(BaseContext):
    """Our basic context we'll use to show a simple scene"""
    '''Without some geometry in the scene to see, it is difficult to know
    if we've actually done anything. So we'll put a simple shape on-screen.
    Assigning to `self.sg` on the context makes the sceneGraph node the
    current scene to display.
    '''
    def OnInit(self):
        super(TestContext,self).OnInit()
        '''OpenGLContext is what is called a "retained mode" rendering
        engine. That is, you setup a graph of node that will be processed
        by the engine to update the scene on each rendering pass. The
        root node is always a sceneGraph and has a "children" field.

        The scenegraph rendered by the engine is 

        The Shape node is a VRML97 node that binds together a piece of
        geometry and an appearance to apply to it. Here we're using a
        physically-based-rendering (pbr) rendering pass which gives us
        metallic and clearcoat features.

        The Teapot geometry is a NURBS version of the famous 
        `Utah Teapot<https://graphics.cs.utah.edu/teapot/>`.
        '''
        self.sg = sceneGraph(
            children=[
                Shape(
                    geometry=Teapot(),
                    appearance=Appearance(material=PBRMaterial(
                        baseColor=(.95,0,0),
                        metallic=1.0,
                        clearcoat=1.0,
                    )),
                ),
                Background(skyColor=(.2,.2,.2)),
                DirectionalLight(
                    direction=(-1,-1,-1),
                ),

            ]
        )

if __name__ == "__main__":
    '''When run as a simple script using glFW, GLUT or PyGame, you 
    generally want to trigger the Context's mainloop. If you are putting
    your context into a larger application with wx, Tk or Qt you likely
    do *not* want to trigger the Context mainloop and should use your
    GUI library's native mainloop system.'''
    TestContext.ContextMainLoop(definition={
        'profile':'core', # use modern OpenGL backend
        # 'renderer': 'pbr', # use vrml97 to use the older, less nice looking renderer
        'size':[1280,720], # arbitrary size for the window
        'title':'Hello 3D World',
    })

'''You can now run your Context from the command like like so::

    $ uv run --pre --with OpenGLContext python ./getting_a_context.py

there are a large number of settings you can control through
:doc:`environment` variables.

    $ OPENGLCONTEXT_BACKEND=pygame python getting_a_context.py
    $ OPENGLCONTEXT_BACKEND=glut python getting_a_context.py
'''