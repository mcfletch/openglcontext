#! /usr/bin/env python
'''=Writing a scene out as glTF, and loading it back=

[bake_demo.py-screen-0001.png Screenshot]

What is on screen was never mounted as authored geometry.  The demo builds a
scene in code, writes it to a `.glb` with
`OpenGLContext.loaders.gltf.writer`, loads that file back with
`OpenGLContext.loaders.gltf.load_gltf`, and mounts *the loaded result*.  The
picture is therefore evidence about the file: whatever survived the write is
what is lit here.

The scene is three things the writer treats differently:

 * *the ground* -- one vertex-coloured patch from the same
   `tiles3d.procedural.terrain_patch` a tileset bake meshes its tiles with,
   under a white material, placed by its node's translation.
 * *the cairn* -- a parent node with four children.  Three of them reference
   **one** boulder mesh at different translations and scales, so the writer
   writes that mesh once and names it three times; the capstone is a second
   mesh under a metallic material of its own.
 * *the ring* -- twelve pebbles as a single node carrying an `InstanceSet`,
   written as `EXT_mesh_gpu_instancing` and loaded back as one
   `InstancedShape` with twelve placements.

The counts printed at startup are taken from the written document's JSON on
one side and from the loaded scenegraph on the other, so the two columns are
independently measured rather than two views of one number.

Press `r` to print the report again, and the usual keys to walk around.  The
written file is left on disk at the path the report names, for opening in any
other glTF viewer.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
# A loaded document wears PBR materials, and only the metallic/roughness pass
# has anything to say to one; without it every surface here draws flat white.
os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

import tempfile

import numpy as np

from OpenGLContext import testingcontext
from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf.writer import GLTFWriter, InstanceSet, SceneNode
from OpenGLContext.loaders.tiles3d.procedural import terrain_patch
from OpenGLContext.scenegraph.basenodes import DirectionalLight, Transform
from OpenGLContext.scenegraph.instancedshape import InstancedShape
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.pbrmesh import PBRMesh
from OpenGLContext.scenegraph.props import rock_mesh
from OpenGLContext.scenegraph.shape import Shape
from OpenGLContext.viewer.environment import horizon_background

BaseContext = testingcontext.getInteractive('glfw')

#: Metres across the ground patch, and how many samples it is meshed at.
GROUND_EXTENT, GROUND_SAMPLES = 24.0, 40

#: The height the ground is *authored* at.  The procedural palette paints by
#: altitude -- sand at the waterline, grass above it -- so the patch is meshed
#: where it is green and the node's translation brings it down to the origin.
GROUND_HEIGHT = 8.0

#: Where the three copies of the one boulder mesh stand, as (x, z, scale).
CAIRN = [(-1.7, 0.4, 1.0), (1.6, -0.7, 0.8), (0.3, -2.4, 1.25)]

#: Pebbles in the instanced ring, and how far out they sit.
RING_COUNT, RING_RADIUS = 12, 5.5


def ground_height(x, z):
    """A gently rolling patch, high enough up to be painted as grass."""
    return 0.5 * np.sin(x * 0.22) * np.cos(z * 0.18) + GROUND_HEIGHT


def authored_scene():
    """The scene to be written, as the writer's own node type.

    Returns the root :class:`SceneNode` list.  Nothing here is a scenegraph
    node: a document is authored out of meshes and placements, and the
    scenegraph is what comes back from loading it.
    """
    half = GROUND_EXTENT / 2.0
    positions, normals, colors, indices = terrain_patch(
        -half, half, -half, half, GROUND_SAMPLES,
        height_fn=ground_height, water_level=None)
    ground = PBRMesh(
        positions=positions, normals=normals, colors=colors, indices=indices,
        material=PBRMaterial(baseColor=(1.0, 1.0, 1.0), metallic=0.0,
                             roughness=1.0, DEF='ground'))

    # One material object shared by the boulders and the pebbles: a material
    # passed twice is written once and referenced twice, as a mesh is.
    stone = PBRMaterial(baseColor=(0.52, 0.49, 0.45), metallic=0.0,
                        roughness=0.9, DEF='stone')
    boulder = rock_mesh(radius=1.3, seed=3, material=stone)
    capstone = rock_mesh(radius=0.75, seed=9, material=PBRMaterial(
        baseColor=(0.78, 0.64, 0.32), metallic=0.9, roughness=0.3, DEF='capstone'))
    pebble = rock_mesh(radius=0.55, seed=5, material=stone)

    cairn = [SceneNode(mesh=boulder, name='boulder-%d' % index,
                       translation=(x, 0.0, z), scale=(scale, scale, scale))
             for index, (x, z, scale) in enumerate(CAIRN)]
    cairn.append(SceneNode(mesh=capstone, name='capstone',
                           translation=(-1.7, 1.45, 0.4)))

    angles = np.linspace(0.0, 2.0 * np.pi, RING_COUNT, endpoint=False)
    ring = InstanceSet(
        translations=np.stack([np.cos(angles) * RING_RADIUS,
                               np.zeros_like(angles),
                               np.sin(angles) * RING_RADIUS], axis=-1),
        # xyzw quaternions turning each pebble about the vertical, so no two
        # copies of the one mesh present the same face.
        rotations=np.stack([np.zeros_like(angles), np.sin(angles / 2.0),
                            np.zeros_like(angles), np.cos(angles / 2.0)], axis=-1),
        scales=np.stack([0.85 + 0.25 * np.cos(angles * 3.0)] * 3, axis=-1))

    return [
        SceneNode(mesh=ground, name='ground',
                  translation=(0.0, -GROUND_HEIGHT, 0.0)),
        SceneNode(name='cairn', children=cairn),
        SceneNode(mesh=pebble, name='ring', instances=ring),
    ]


def written_counts(document):
    """What the written document says it holds, read out of its JSON."""
    accessors = document.get('accessors', [])
    meshes = document.get('meshes', [])
    vertices = triangles = instances = 0
    for mesh in meshes:
        for primitive in mesh['primitives']:
            vertices += accessors[primitive['attributes']['POSITION']]['count']
            if 'indices' in primitive:
                triangles += accessors[primitive['indices']]['count'] // 3
    for node in document.get('nodes', []):
        gpu = node.get('extensions', {}).get('EXT_mesh_gpu_instancing')
        if gpu:
            instances += accessors[gpu['attributes']['TRANSLATION']]['count']
    return {
        'nodes': len(document.get('nodes', [])),
        'meshes': len(meshes),
        'materials': len(document.get('materials', [])),
        'vertices': vertices,
        'triangles': triangles,
        'instances': instances,
        'buffer bytes': document['buffers'][0]['byteLength'],
    }


def loaded_counts(scene):
    """The same figures, counted over the scenegraph the loader built."""
    transforms, shapes = [], []
    def walk(node):
        for child in getattr(node, 'children', None) or []:
            if isinstance(child, Shape):
                shapes.append(child)
            elif isinstance(child, Transform):
                transforms.append(child)
            walk(child)
    walk(scene.group)
    # By identity: a mesh written once and referenced three times loads as one
    # PBRMesh under three Shapes, which is the dedup arriving intact.
    geometries = {id(shape.geometry): shape.geometry for shape in shapes}
    materials = {id(shape.appearance.material) for shape in shapes}
    instances = sum(len(shape.placements) for shape in shapes
                    if isinstance(shape, InstancedShape))
    arrays = ('positions', 'normals', 'texcoords', 'tangents', 'colors', 'indices')
    return {
        'nodes': len(transforms),
        'meshes': len(geometries),
        'materials': len(materials),
        'vertices': sum(len(mesh.positions) for mesh in geometries.values()),
        'triangles': sum(len(mesh.indices) // 3 for mesh in geometries.values()
                         if mesh.indices is not None),
        'instances': instances,
        'buffer bytes': sum(
            getattr(mesh, name).nbytes for mesh in geometries.values()
            for name in arrays if getattr(mesh, name, None) is not None),
    }


class TestContext(BaseContext):
    """Author, write, load, and mount what came back."""

    initialPosition = (0, 4.0, 11.5)
    initialOrientation = (1, 0, 0, -0.26)

    def OnInit(self):
        BaseContext.OnInit(self)
        print(__doc__)
        writer = GLTFWriter()
        for node in authored_scene():
            writer.add_node(node)
        directory = tempfile.mkdtemp(prefix='gltf-writer-demo-')
        self.path = os.path.join(directory, 'cairn.glb')
        data = writer.write(self.path)
        self.written = written_counts(writer.document())
        self.size = len(data)

        scene = load_gltf(self.path)
        self.read = loaded_counts(scene)
        self.report()

        # The sky and the lights are the demo's own: a document written from
        # meshes carries no environment, and an unlit boulder is a silhouette.
        # A key from over the viewer's left shoulder, a cool fill opposite it.
        self.sg = Transform(children=[
            horizon_background(),
            DirectionalLight(direction=(-0.4, -0.75, -0.5), intensity=1.1),
            DirectionalLight(direction=(0.6, -0.25, 0.6), intensity=0.35,
                             color=(0.55, 0.66, 0.9)),
            scene.group,
        ])
        self.addEventHandler('keypress', name='r', function=self.OnReport)

    def OnReport(self, event):
        self.report()

    def report(self):
        """The written file and what each side of the round trip counts."""
        print('wrote %s' % (self.path,))
        print('%-12s %12s %12s' % ('', 'written', 'read back'))
        for key in ('nodes', 'meshes', 'materials', 'vertices', 'triangles',
                    'instances'):
            print('%-12s %12s %12s' % (key, f'{self.written[key]:,}',
                                       f'{self.read[key]:,}'))
        print('%-12s %12s %12s' % ('bytes', f"{self.written['buffer bytes']:,}",
                                   f"{self.read['buffer bytes']:,}"))
        print('%s bytes on disk: that buffer, the JSON describing it, and the\n'
              'GLB headers. The loaded arrays weigh more because an index that '
              'is 16 bits\nin the file is 32 in the buffer the GPU is handed.'
              % f'{self.size:,}')


if __name__ == "__main__":
    TestContext.ContextMainLoop()
