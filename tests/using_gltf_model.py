#! /usr/bin/env python
'''=Loading a model=

[using_gltf_model.py-screen-0001.png Screenshot]

Loading a glTF or GLB file into a scene, and putting the camera where the
model can be seen.  The model here is `BoomBox` from the Khronos sample
catalogue (CC0); a path to a file of your own is loaded the same way.
'''
'''A glTF model describes its surfaces the way the PBR renderer reads them —
base colour, metalness, roughness and the maps that vary them — so that is the
renderer to draw it with.  It is chosen by the environment
(``OPENGLCONTEXT_RENDERER=pbr python using_gltf_model.py``), which a script
can set for itself as long as it does so before the engine is imported.
``oglc-view`` does the same thing.'''
import os
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
'''``load_gltf`` reads a ``.gltf`` or ``.glb`` and returns a ``GLTFScene``.
Two of its attributes are used below: ``group``, the ``Transform`` holding
what was in the file, and ``radius``, the radius of the sphere that contains
it.'''
from OpenGLContext.loaders.gltf import load_gltf, sample_model_url
from OpenGLContext.loaders.resolver import fetch_to_cache
'''The scenegraph nodes come from ``basenodes``, which holds every node type
the engine registers under the name VRML97 gives it.'''
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)

'''``sample_model_url`` names a model in the Khronos sample catalogue and
``fetch_to_cache`` downloads it once into the user's asset cache, returning
the path it was written to.  Loading a file already on disk needs neither:
``load_gltf('mymodel.glb')``.'''
MODEL = 'BoomBox'


class TestContext(BaseContext):
    '''The camera starts three units back along Z, looking down -Z at the
    origin, which is where the model is put below.'''
    initialPosition = (0, 0, 3)

    def OnInit(self):
        scene = load_gltf(fetch_to_cache(sample_model_url(MODEL)))
        '''A model carries the units it was authored in, and they vary: this
        one is a tenth of a metre across, a character model may be two metres,
        a terrain tile a thousand.  Scaling by ``1 / radius`` makes any of them
        about two units across, which is what lets one camera position show
        any of them.'''
        scale = 1.0 / scene.radius
        model = Transform(
            scale=(scale, scale, scale),
            translation=[-value * scale for value in scene.center],
            children=[scene.group],
        )
        '''The scene is a ``sceneGraph`` of the model, a light to see it by and
        a background to put behind it.  Assigning it to ``self.sg`` is what
        gives the context something to draw.'''
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.15, 0.17, 0.2)]),
            DirectionalLight(direction=(-0.4, -0.6, -1.0), intensity=1.0),
            model,
        ])
        print('%s: %d root nodes, radius %.3f in the file' % (
            MODEL, len(scene.group.children), scene.radius,
        ))
        '''The loaded scene also carries the cameras and the animations the
        file declared, if it has any: ``scene.cameras`` and
        ``scene.animations``.  :doc:`Playing an animation <using_clips>` is
        the next tutorial.'''


if __name__ == "__main__":
    TestContext.ContextMainLoop()
