#! /usr/bin/env python
'''=Loading a glTF model=

[using_gltf_model.py-screen-0001.png Screenshot]

Loading a glTF or GLB file into a scene, framing it, reaching one object
inside it, and moving what was loaded.  The model is `Lantern` from the
Khronos sample catalogue (CC0), which is four objects in one file -- a
pole, a chain, a lantern and the root that holds them; a path to a file of
your own is loaded the same way.

glTF 2.0 is the format this engine is built around: meshes, materials,
skins, animations, cameras and lights in one file, with the same meaning
here as in the tool that wrote it.  *Making one in Blender* at the foot of
this page is how to produce one.

Keys:

    space   stop and start the movement
'''
'''A glTF model describes its surfaces the way the PBR renderer reads them —
base colour, metalness, roughness and the maps that vary them — so that is the
renderer to draw it with.  It is chosen by the environment
(``OPENGLCONTEXT_RENDERER=pbr python using_gltf_model.py``), which a script
can set for itself as long as it does so before the engine is imported.
``oglc-view`` does the same thing.'''
import math
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
from OpenGLContext.events.timer import Timer
'''The scenegraph nodes come from ``basenodes``, which holds every node type
the engine registers under the name VRML97 gives it.'''
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, sceneGraph,
)

'''``sample_model_url`` names a model in the Khronos sample catalogue and
``fetch_to_cache`` downloads it once into the user's asset cache, returning
the path it was written to.  Loading a file already on disk needs neither:
``load_gltf('mymodel.glb')``.'''
MODEL = 'Lantern'
#: The object inside the file to swing, by the name the file gives it.
PART = 'LanternPole_Lantern'
#: Seconds for one turn of the model, and for one swing of the lantern.
PERIOD = 10.0
SWING = 2.5


class TestContext(BaseContext):
    '''The camera starts three units back along Z, looking down -Z at the
    origin, which is where the model is put below.'''
    initialPosition = (0, 0, 3)

    def OnInit(self):
        scene = load_gltf(fetch_to_cache(sample_model_url(MODEL)))
        '''``scene.group`` is an ordinary ``Transform``, so framing the model
        is writing its own fields rather than wrapping it in something.

        A model carries the units it was authored in, and they vary: this one
        is some thirty units tall, a character model may be two metres, a
        terrain tile a thousand.  Scaling by ``1 / radius`` makes any of them
        about two units across, which is what lets one camera position show
        any of them.

        ``center`` is the point a ``Transform`` scales and rotates *about*, so
        putting the model's own centre in it makes the scale shrink the model
        where it stands, and the turntable below spin it on its own axis
        rather than swinging it around the origin.  ``translation`` then
        brings that centre to the origin, which is what the camera is looking
        at.'''
        self.model = scene.group
        self.scale = 1.0 / scene.radius
        self.centre = tuple(float(value) for value in scene.center)
        self.model.center = self.centre
        self.model.scale = (self.scale, self.scale, self.scale)
        self.model.translation = tuple(-value for value in self.centre)

        '''The scene is a ``sceneGraph`` of the model, a light to see it by and
        a background to put behind it.  Assigning it to ``self.sg`` is what
        gives the context something to draw.'''
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.15, 0.17, 0.2)]),
            DirectionalLight(direction=(-0.4, -0.6, -1.0), intensity=1.0),
            self.model,
        ])
        print('%s: %d root nodes, radius %.3f in the file' % (
            MODEL, len(self.model.children), scene.radius,
        ))

        '''*One object out of several.*  A file is usually more than one thing,
        and ``scene.node_names`` is what the file calls each of them -- the
        names the modeller typed, by the document's node number::

            {0: 'LanternPole_Body', 1: 'LanternPole_Chain',
             2: 'LanternPole_Lantern', 3: 'Lantern'}

        ``scene.sceneGraph.getDEF(name)`` answers the ``Transform`` built for
        one of them.  It is a node of the loaded scene, not a copy, so writing
        its fields moves that part and nothing else.'''
        print('%s holds: %s' % (MODEL, ', '.join(scene.node_names.values())))
        self.part = scene.sceneGraph.getDEF(PART)
        '''``scene.node_transforms`` is the same thing by node number, for a
        file whose names are not unique or not there at all.'''

        self.running = True
        self.timer = Timer(duration=PERIOD, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        self.addEventHandler('keypress', name=' ', function=self.OnToggle)
        print(__doc__)

    def OnFraction(self, event):
        '''*Moving what was loaded.*  The three fields of the loaded group are
        written here, every frame: ``rotation`` turns it on the spot,
        ``translation`` carries it (added to the centring above, so the model
        bobs around where the camera is pointed rather than jumping off), and
        ``scale`` multiplies the framing scale rather than replacing it.

        Nothing else has to be told: a field is observed, so writing one marks
        what has to be drawn again.  :doc:`Animating a transform
        <using_animation>` is the timer itself in detail.'''
        if not self.running:
            return
        turn = 2.0 * math.pi * event.fraction()
        self.model.rotation = (0, 1, 0, turn)
        '''``translation`` is applied after the scale, so a bob of 0.08 is
        0.08 of the framed model rather than 0.08 of the units the file was
        authored in.'''
        bob = 0.08 * math.sin(turn * 2.0)
        self.model.translation = (-self.centre[0],
                                  -self.centre[1] + bob,
                                  -self.centre[2])
        breath = self.scale * (1.0 + 0.03 * math.sin(turn * 3.0))
        self.model.scale = (breath, breath, breath)
        '''*Moving one object inside it.*  The lantern swings on its chain:
        the same kind of write, to the node ``getDEF`` answered with, in the
        coordinates its own parent gives it.'''
        if self.part is not None:
            swing = 0.25 * math.sin(2.0 * math.pi * PERIOD / SWING
                                    * event.fraction())
            self.part.rotation = (0, 0, 1, swing)

    def OnToggle(self, event):
        self.running = not self.running


'''The file may carry cameras and animations of its own as well:
``scene.cameras`` is one entry per camera it defines, and
``scene.animations`` the clips a rigged model was authored with --
:doc:`Playing a canned animation <using_clips>` plays those.'''

'''_Making one in Blender_

Blender writes glTF 2.0 without an add-on to install: *File > Export > glTF
2.0*.  Its manual page for the exporter is
[https://docs.blender.org/manual/en/latest/addons/scene_gltf2.html glTF 2.0
in the Blender manual], and what follows is the part of it that decides
whether a file loads here looking as it did there.

Which file to write - the format menu offers three.  *glTF Binary
(.glb)* puts the mesh, the materials and the textures in one file and is
the one to prefer -- nothing to lose track of, and the only thing to copy
into a game's assets.  *glTF Separate (.gltf + .bin + textures)* is the
same data as a folder, which is what to export when the textures are
edited after the fact.  ``load_gltf`` reads either.

Units and axes - one Blender unit is one metre, which is what glTF
measures in, so a model built to scale arrives at scale.  Blender is Z-up
and glTF is Y-up; the exporter turns the scene as it writes, so nothing has
to be rotated by hand.  What does have to be applied is the object's own
transform (*Object > Apply > All Transforms*) if the scale on it is not
what the game should see.

Materials - use the Principled BSDF.  Its Base Color, Metallic,
Roughness, Normal, Emission and Alpha -- values or image textures -- are
what the exporter writes into glTF's metallic-roughness material, which is
what the :doc:`PBR renderer </pbr>` reads back.  A node graph doing
something else exports as the nearest flat values it can find, so a surface
that depends on procedural texture nodes wants baking to an image first.

What goes in the file - *Include > Selected Objects* limits the export to
the selection; *Data > Mesh > Apply Modifiers* writes the mesh as it looks
with its modifiers on rather than the base cage.  Cameras and punctual
lights are exported under *Include* as well, and arrive as
``scene.cameras`` and as lights in the scenegraph.

A rigged character - its armature exports as a skin and its actions as
named animations -- which is :doc:`Playing a canned animation
<using_clips>`.

Smaller files - *Compression* applies Draco to the meshes.  Loading one
needs the ``draco`` extra (``pip install "OpenGLContext[draco]"``).

Levels of detail - the add-on in ``openglcontext-editor`` cuts a chain of
coarser meshes from the selected object and writes it as ``MSFT_lod``, which
this engine switches between by distance: :ref:`making levels in Blender
<blender>`.
'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()
