#! /usr/bin/env python
'''=Loading a glTF model=

[using_gltf_model.py-screen-0001.png Screenshot]

Most of the time you will not want to hand-build your scene from primitive
objects or calculate the positions of vertices in meshes with a calculator.
Tools such as `Blender<https://www.blender.org/>`_ are freely available,
provide extensive tutorials and pre-made worlds, and can export into the
glTF format that OpenGLContext supports.
'''
import math
from OpenGLContext.context import Context as BaseContext
'''OpenGLContext includes a small index of glTF files that are maintained
on GitHub by Khronos as demonstrations and test vectors. These are what
configures the `oglc-gltf-demo` command. The :func:`sample_model_url` function
looks up the URL in that index by name.
'''
from OpenGLContext.loaders.gltf import sample_model_url
'''The :py:class:`OpenGLContext.loader.sceneloader.LoadRequest` is what the scene 
loader returns. You normally want to access the `result` member on it. The
GLTFScene is the gltf loader's internal scenegraph model.'''
import typing 
if typing.TYPE_CHECKING:
    from OpenGLContext.loaders import LoadRequest
    from OpenGLContext.loaders.gltf import GLTFScene
'''Import some scene description nodes from the scenegraph'''
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
    Shape,Cylinder,Transform,Appearance,Material,
)
'''This is the index into the sample urls we are going to use for our
demo. It is a wood-and-iron lamp post.'''
MODEL = 'Lantern'
#: The object inside the file to swing, by the name the file gives it.
PART = 'LanternPole_Lantern'
#: Seconds for one turn of the model, and for one swing of the lantern.
PERIOD = 10.0
SWING = 2.5


class TestContext(BaseContext):
    '''The camera starts three units back along Z, looking down -Z at the
    origin, which is where the model is put below.'''
    initialPosition = (0, 1.65, 2)

    def OnInit(self):
        '''Request that the glTF document be loaded from the URL for this model'''
        self.sceneLoader.load(sample_model_url(MODEL), on_loaded=self.OnSceneLoaded)
    def OnSceneLoaded(self, result:'LoadRequest'):
        """Handle the scene loading from the network"""
        '''Result is a LoadRequest object, and since this is the success callback
        it should have a non-null `.result` member, which, because it is a 
        glTF model, should be a GLTFScene object'''
        scene:'GLTFScene' = result.result
        
        '''`scene.group` is a Transform object, with fields translation,
        rotation, and scale, so it can be directly moved around the scene
        as necessary without further wrapping.
        '''
        self.model = scene.group
        self.centre = tuple(float(value) for value in scene.center)
        '''While glTF is supposed to be authored in a 1 unit = 1 meter scale,
        there are lots of models that are either not in that scale, or where
        we would like to make the model a different scale. In this case, the
        model appears to be in roughly decimeter scale (1 unit is 10cm), where
        the model is 30 units tall when it should be around 3m tall.

        The bottom center of the pole is 0,0,0, so by default the transform of the 
        pole works to scale the sample world down to 1m scale just with a 
        1/10th scale.
        '''
        self.model.scale = (.1,.1,.1)

        '''As with the scene we created in :doc:`getting_a_context` we need to
        assign a sceneGraph to `self.sg` to show the world. To make the world
        slightly more interesting, we'll add a light, a dark sky, and a small
        plane on which to see the shadows...
        '''
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.15, 0.17, 0.2)]),
            DirectionalLight(direction=(-0.4, -0.6, -1.0), intensity=1.0),
            self.model,
            Transform(
                translation=(0,-1,0),
                children =[
                    Shape(
                        geometry=Cylinder(radius=20,height=2),
                        appearance=Appearance(
                            material=Material(diffuseColor=(.5,.5,.5))
                        ),
                    )
                ],
            )
        ])
        '''To add a little more interest to the scene, let's make the light
        dangling from the chain sway back and forth a bit. Most formats, and
        particularly glTF and VRML97 are composed of sub-objects which are
        generally addressable by name.
        
        In the glTF loader, you can introspect the names in `scene.node_names`
        which is a dictionary mapping object-index to named node's names. 
        In the model we're loading, the lantern is named "LanternPole_Lantern".

        Here we're going to save a reference to the lantern for future reference
        when we want to animate it. There's a convenience method in the sceneGraph
        to find the named nodes within it:
        '''
        self.part = scene.sceneGraph.getDEF(PART)
        '''The part is not rigged to rotate around it's attachment point, so
        here we adjust that attachment point up by 2.3 units in the model's scale.
        Again, because we're adjusting something *inside* the model's overall 
        transform, we need to work in the *model's* scale. So while 2m at the
        root of the scene would be far too much, with the 1/10th scale we are
        applying, we get about 23cm, which is just about enough to center the 
        rotation around the ring on the top of the lantern.
        '''
        self.part.center = self.part.center + (0,2.3,0)

        self.timer = self.createTimer(duration=PERIOD, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.running = True
        self.addEventHandler('keypress', name=' ', function=self.OnToggle)


    def OnFraction(self, event):
        """Update the rotation of the lamp around its new pivot point"""
        '''
        We'll update the swing of the lamp every frame so that it
        smoothly swings back and forth based on a simple sine wave
        calculation. Assigning to the rotation field of the part's
        transform causes it to update its position in the world,
        clearing any caches that hold that position.
        '''
        if not self.running:
            return
        
        if self.part is not None:
            swing = 0.25 * math.sin(2.0 * math.pi * PERIOD / SWING
                                    * event.fraction())
            self.part.rotation = (0, 0, 1, swing)

    def OnToggle(self, event):
        """The keyboard callback handler, allows us to stop the swing"""
        '''The individual timer is paused, so that we can resume
        the animation at the point where it stopped swinging.
        The overall scene time will continue to run (for other 
        animations).
        '''
        if self.running:
            self.timer.pause()
        else:
            self.timer.resume()
        self.running = not self.running

if __name__ == "__main__":
    '''We need the (default) pbr renderer to handle glTF
    PBR worlds. Here we are explicitly requesting the pbr
    renderer.'''
    TestContext.ContextMainLoop(definition={
        'renderer':'pbr',
    })


'''Blender Exports

Blender writes glTF 2.0 without any add-ons. You can use
**File > Export > glTF** to export a standard glTF world that
OpenGLContext should load well. You want to use the 
`Principled BSDF` material in Blender to best render
in glTF models using the `pbr` renderer in OpenGLContext.

There are many extensions to glTF that OpenGLContext also supports,
which may not be fully supported in Blender. The `openglcontext-editor`
package has an experimental extension that allows for writing
LOD (level of detail) chains directly into your glTF files using the
``MSFT_lod`` extension.
'''

