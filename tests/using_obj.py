#! /usr/bin/env python
'''=Loading an OBJ model=

[using_obj.py-screen-0001.png Screenshot]

Wavefront OBJ is the plainest of the formats the engine reads: vertices,
normals, texture coordinates and faces as lines of text, with the surface
colours in a ``.mtl`` file beside it.  It carries no animation, no cameras
and no lights -- which makes it a good place to see what a program adds to
a loaded model rather than what the file brought.

The model here is written out at start-up, so what the loader reads is in
this file rather than beside it.  Loading one from disk is the same call
with a path to it.

Keys:

    space   stop and start the turntable
'''
import math
import os
import tempfile

from OpenGLContext import testingcontext
'''One loader for every format: ``Loader.load`` looks at the name, picks
the handler registered for it, and answers a scenegraph.  An ``.obj`` and a
``.wrl`` are the same call -- :doc:`Loading a VRML97 model <using_vrml97>`
is the other one.'''
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.events.timer import Timer
from OpenGLContext.scenegraph.basenodes import (
    Background, DirectionalLight, Transform, sceneGraph,
)

BaseContext = testingcontext.getInteractive()

#: Seconds for one turn of the model.
PERIOD = 8.0

#: A house, as OBJ writes one: ``v`` a vertex, ``vn`` a normal, ``f`` a face
#: of ``vertex//normal`` indices counted from one, ``usemtl`` the material
#: the faces after it are drawn with, and ``mtllib`` the file those
#: materials are in.
MODEL = """\
mtllib house.mtl

v -1 0 1
v 1 0 1
v 1 0 -1
v -1 0 -1
v -1 1 1
v 1 1 1
v 1 1 -1
v -1 1 -1
v 0 1.8 1
v 0 1.8 -1

vn 0 0 1
vn 1 0 0
vn 0 0 -1
vn -1 0 0
vn 0 -1 0
vn 0 0.55 0.83
vn 0 0.55 -0.83

usemtl walls
f 1//1 2//1 6//1 5//1
f 2//2 3//2 7//2 6//2
f 3//3 4//3 8//3 7//3
f 4//4 1//4 5//4 8//4
f 4//5 3//5 2//5 1//5

usemtl roof
f 5//6 6//6 9//6
f 7//7 8//7 10//7
f 6//6 7//6 10//6 9//6
f 8//7 5//7 9//7 10//7
"""

#: The materials it names.  ``Kd`` is the diffuse colour, ``Ka`` ambient,
#: ``Ks`` specular and ``Ns`` the shininess; ``map_Kd`` would name a texture.
MATERIALS = """\
newmtl walls
Kd 0.82 0.78 0.70
Ka 0.10 0.10 0.10
Ks 0.15 0.15 0.15
Ns 20

newmtl roof
Kd 0.55 0.22 0.18
Ka 0.08 0.04 0.03
Ks 0.10 0.10 0.10
Ns 10
"""


class TestContext(BaseContext):
    initialPosition = (0, 1.6, 6)
    initialOrientation = (-1, 0, 0, 0.16)

    def OnInit(self):
        path = write_model()
        '''The material file is found beside the model, by the name the
        ``mtllib`` line gives -- which is why an OBJ moved without its
        ``.mtl`` arrives grey.'''
        loaded = Loader.load(path)
        print('%s: %d root nodes' % (os.path.basename(path),
                                     len(loaded.children)))
        '''The file's nodes are mounted under a ``Transform`` of this
        program's own.  OBJ says nothing about scale or orientation, so what
        the file measures in is something the model's author has to be asked
        -- or worked out from the size of what arrives.'''
        self.model = Transform(children=list(loaded.children))
        self.sg = sceneGraph(children=[
            Background(skyColor=[(0.12, 0.14, 0.17)]),
            DirectionalLight(direction=(-0.5, -0.7, -0.5)),
            # A dim fill from the other side, so the wall facing away from the
            # key light is shaded rather than black.
            DirectionalLight(direction=(0.7, -0.3, 0.5), intensity=0.45,
                             color=(0.8, 0.85, 1.0)),
            self.model,
        ])
        '''Nothing in the file moves, so the movement is this program's:
        a turntable, from a ``Timer``, as in
        :doc:`Animating a transform <using_animation>`.'''
        self.running = True
        self.timer = Timer(duration=PERIOD, repeating=1)
        self.timer.addEventHandler('fraction', self.OnFraction)
        self.timer.register(self)
        self.timer.start()
        self.addEventHandler('keypress', name=' ', function=self.OnToggle)
        print(__doc__)

    def OnFraction(self, event):
        if self.running:
            self.model.rotation = (0, 1, 0, 2.0 * math.pi * event.fraction())

    def OnToggle(self, event):
        self.running = not self.running


def write_model():
    """The model and its materials, in a temporary directory; returns the path."""
    directory = tempfile.mkdtemp(prefix='oglc-obj-')
    path = os.path.join(directory, 'house.obj')
    with open(path, 'w', encoding='utf-8') as handle:
        handle.write(MODEL)
    with open(os.path.join(directory, 'house.mtl'), 'w', encoding='utf-8') as handle:
        handle.write(MATERIALS)
    return path


'''_What OBJ does not carry_

The format is geometry and surface colour, and a program supplies the rest:

* No animation - anything that moves is moved from code, or the model is
  converted to glTF, which does carry it --
  :doc:`Playing a canned animation <using_clips>`.
* No lights and no camera - the scene above provides both.
* No units and no up axis - a model may arrive a thousand times too large or
  lying on its side; a scale and a rotation on the ``Transform`` above it
  are where that is settled.
* No skinning - a rigged character wants glTF.

For anything beyond a static prop, glTF is the format to convert to --
Blender reads OBJ and writes glTF, and
:doc:`Loading a glTF model <using_gltf_model>` covers the export.
'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()
