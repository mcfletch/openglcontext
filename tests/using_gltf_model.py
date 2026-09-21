#! /usr/bin/env python
'''=Loading a glTF model=

[using_gltf_model.py-screen-0001.png Screenshot]

Loading a glTF or GLB file into a scene, and putting the camera where the
model can be seen.  The model here is `BoomBox` from the Khronos sample
catalogue (CC0); a path to a file of your own is loaded the same way.

glTF 2.0 is the format this engine is built around: meshes, materials,
skins, animations, cameras and lights in one file, with the same meaning
here as in the tool that wrote it.  *Making one in Blender* at the foot of
this page is how to produce one.
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


'''_Making one in Blender_

Blender writes glTF 2.0 without an add-on to install: *File > Export > glTF
2.0*.  Its manual page for the exporter is
[https://docs.blender.org/manual/en/latest/addons/scene_gltf2.html glTF 2.0
in the Blender manual], and what follows is the part of it that decides
whether a file loads here looking as it did there.

*Which file to write.*  The format menu offers three.  **glTF Binary
(.glb)** puts the mesh, the materials and the textures in one file and is
the one to prefer -- nothing to lose track of, and the only thing to copy
into a game's assets.  **glTF Separate (.gltf + .bin + textures)** is the
same data as a folder, which is what to export when the textures are
edited after the fact.  ``load_gltf`` reads either.

*Units and axes.*  One Blender unit is one metre, which is what glTF
measures in, so a model built to scale arrives at scale.  Blender is Z-up
and glTF is Y-up; the exporter turns the scene as it writes, so nothing has
to be rotated by hand.  What does have to be applied is the object's own
transform (*Object > Apply > All Transforms*) if the scale on it is not
what the game should see.

*Materials.*  Use the **Principled BSDF**.  Its Base Color, Metallic,
Roughness, Normal, Emission and Alpha -- values or image textures -- are
what the exporter writes into glTF's metallic-roughness material, which is
what the :doc:`PBR renderer </pbr>` reads back.  A node graph doing
something else exports as the nearest flat values it can find, so a surface
that depends on procedural texture nodes wants baking to an image first.

*What goes in the file.*  *Include > Selected Objects* limits the export to
the selection; *Data > Mesh > Apply Modifiers* writes the mesh as it looks
with its modifiers on rather than the base cage.  Cameras and punctual
lights are exported under *Include* as well, and arrive as
``scene.cameras`` and as lights in the scenegraph.

*A rigged character* exports its armature as a skin and its actions as
named animations -- which is :doc:`Playing a canned animation
<using_clips>`.

*Smaller files.*  *Compression* applies Draco to the meshes.  Loading one
needs the ``draco`` extra (``pip install "OpenGLContext[draco]"``).

*Levels of detail.*  The add-on in ``openglcontext-editor`` cuts a chain of
coarser meshes from the selected object and writes it as ``MSFT_lod``, which
this engine switches between by distance: :ref:`making levels in Blender
<blender>`.
'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()
