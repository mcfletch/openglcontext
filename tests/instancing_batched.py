#! /usr/bin/env python
'''=Instanced batching (the pass collapses repeated shapes)=

[instancing_batched.py-screen-0001.png Screenshot]

The other instancing demos in this directory (`shader_instanced.py` and
friends) drive `glDrawElementsInstanced` by hand.  This one shows the
thing a game actually gets for free: the **render pass** noticing that
many shapes are the same and drawing each set in a single call, without
the geometry nodes knowing anything about it.

Three fields of 96 spheres and a row of 8 boxes -- 296 shapes:

 * *left, blue* -- 96 `Shape` nodes that all reference **one** `Sphere`
   node.  This is the VRML `USE` / glTF shared-mesh case, and the batcher
   spots it by object identity.
 * *middle, orange* -- 96 shapes each with **its own** `Sphere` node of
   the same radius.  Nothing is shared, so identity finds nothing; these
   collapse because the batcher also keys on geometry *content*
   (`instanceContentKey`).  `OPENGLCONTEXT_INSTANCE_COLLAPSE=off` turns
   that half off and this field alone falls back to one draw per sphere.
 * *right, green* -- 96 more of the shared sphere, but under a second
   material.  A group is geometry **and** a compatible appearance, so
   this is a third group rather than joining the first.
 * *the boxes* -- a different geometry, hence a group of their own.

Press `i` to turn instancing off and on. The counts are printed whenever
they change, so the collapse is legible without reading the picture:

    instancing ON   296 of 296 shapes -> 4 draws (296 instances in 4 groups)
    instancing OFF  296 of 296 shapes -> 296 draws (0 instances in 0 groups)

The first number is what survived frustum culling, which runs before
batching; turn away from the fields and both numbers fall together.

With `OPENGLCONTEXT_INSTANCE_COLLAPSE=off` the same scene draws in 106:
the two shared-node fields still batch into 2, and the 96 separate
spheres and 8 separate boxes each cost a draw of their own.

Press `c` to print the same counts on demand. The usual keys walk around.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_PROFILE', 'core')
os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, DirectionalLight, Material, Shape, Sphere, Transform,
)

BaseContext = testingcontext.getInteractive('glfw')

#: Spheres per field, as columns x rows.  Enough that one draw against one
#: per shape is an obvious difference rather than a subtle one.
COLUMNS, ROWS = 8, 12

#: Radius every sphere in the demo is built at.  The middle field relies on
#: these being *equal but separate* nodes, which is what content batching is
#: for, so this is deliberately one constant rather than a per-field value.
RADIUS = 0.32

#: Shapes the scene is built from: three fields of spheres and a row of boxes.
#: The pass reports how many of them survived culling, which is a little fewer
#: whenever some are off the edge of the window.
SCENE_SHAPES = 3 * COLUMNS * ROWS + COLUMNS


def _field(x_offset, material, shared):
    """One field of spheres.

    shared -- a Sphere node every Shape here references, for the identity
        case; None to give each Shape its own equal-but-separate Sphere,
        which is what exercises content batching.
    """
    children = []
    for column in range(COLUMNS):
        for row in range(ROWS):
            geometry = shared if shared is not None else Sphere(radius=RADIUS)
            children.append(Transform(
                translation=(x_offset + column * 0.85, row * 0.85, 0.0),
                children=[Shape(geometry=geometry,
                                appearance=Appearance(material=material))]))
    return children


class TestContext(BaseContext):
    """Four instance groups, and a key that stops them being groups."""

    initialPosition = (2.4, 4.6, 22)

    def OnInit(self):
        BaseContext.OnInit(self)
        blue = Material(diffuseColor=(0.25, 0.45, 0.85))
        orange = Material(diffuseColor=(0.9, 0.5, 0.15))
        green = Material(diffuseColor=(0.3, 0.7, 0.35))
        grey = Material(diffuseColor=(0.5, 0.5, 0.55))

        # Two lights, so a sphere reads as a sphere rather than a disc: a key
        # from over the viewer's shoulder and a dim fill from the other side.
        children = [
            DirectionalLight(direction=(-0.3, -0.6, -0.8), intensity=0.9),
            DirectionalLight(direction=(0.7, -0.2, 0.5), intensity=0.35,
                             color=(0.6, 0.7, 1.0)),
        ]
        # Left: one geometry node, referenced 96 times.
        children.extend(_field(-9.0, blue, shared=Sphere(radius=RADIUS)))
        # Middle: 96 separate geometry nodes of equal content.
        children.extend(_field(-1.0, orange, shared=None))
        # Right: the shared node again, under a different material, so the
        # appearance rather than the geometry is what splits the group.
        children.extend(_field(7.0, green, shared=Sphere(radius=RADIUS)))
        # A row of boxes: a different geometry, so a fourth group.
        for column in range(COLUMNS):
            children.append(Transform(
                translation=(-9.0 + column * 1.9, -1.6, 0.0),
                children=[Shape(geometry=Box(size=(0.6, 0.6, 0.6)),
                                appearance=Appearance(material=grey))]))

        self.sg = Transform(children=children)
        self.addEventHandler('keypress', name='i', function=self.OnToggle)
        self.addEventHandler('keypress', name='c', function=self.OnCounts)
        #: What was last printed, so an unchanged frame stays quiet.
        self._reported = None
        print(__doc__)

    def OnToggle(self, event):
        """Instancing is a ContextDefinition field, so this takes effect next frame."""
        definition = self.contextDefinition
        definition.instancing = not definition.instancing
        self.triggerRedraw(1)

    def OnCounts(self, event=None):
        self._report(force=True)

    def _report(self, force=False):
        stats = getattr(self, 'renderStats', None)
        if stats is None:
            return
        # stats.shapes is what survived frustum culling, which happens
        # before batching -- so it is usually a little under the scene total.
        line = ('instancing %-4s %d of %d shapes -> %d draws '
                '(%d instances in %d groups)'
                % ('ON' if self.contextDefinition.instancing else 'OFF',
                   stats.shapes, SCENE_SHAPES, stats.draws, stats.instances,
                   stats.instanceGroups))
        if force or line != self._reported:
            self._reported = line
            print(line)

    def OnDraw(self, *args, **named):
        drawn = super(TestContext, self).OnDraw(*args, **named)
        # After the frame, so the counts are the ones just rendered.
        self._report()
        return drawn


if __name__ == "__main__":
    TestContext.ContextMainLoop()
