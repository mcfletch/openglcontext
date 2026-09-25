#! /usr/bin/env python
'''=Mirrors: a room that reflects itself=

[mirrors_room.py-screen-0001.png Screenshot]

A small brick room with a silvered mirror on the far wall, two small
mirrors on the right wall, a polished marble floor and a pool of still water.
Every one of them is an ordinary surface whose material carries a
`PlanarReflector`; the render pass does the rest. The reference for all of it
is the [../reflections.html Reflections] page.

Keys:

 * `r` -- reflections on and off (`ContextDefinition.planarReflections`)
 * `b` -- the mirror views a frame may draw: the strategy's own, then 1 and 2
 * `p` -- print what the last frame's reflections cost
 * `alt+f` -- the developer overlay, whose Render section shows the same
'''
import os

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.scenegraph import basenodes, surfaces
from OpenGLContext.scenegraph.pbrmaterial import PBRMaterial
from OpenGLContext.scenegraph.reflector import PlanarReflector
from OpenGLContext.scenegraph.water import STILL, water_surface
from OpenGLContext.viewer.environment import sky_background

'''The room is 8 m wide, 3 m high and 10 m deep, the camera stands near the
open end, and the far wall is at z = -5.'''
WIDTH, HEIGHT, DEPTH = 8.0, 3.0, 10.0

'''The mirror views a frame may draw, which `b` steps through: 0 is the
multi-view strategy's own budget.'''
BUDGETS = (0, 1, 2)


class TestContext(BaseContext):
    initialPosition = (-2.5, 1.6, 4.0)
    initialOrientation = (0.0, 1.0, 0.0, -0.5)

    def OnInit(self):
        '''=Making a surface a mirror=

        A mirror is a material with a `PlanarReflector` in its `reflector`
        field. Its plane is fitted to the mesh it is drawn on, so any flat mesh
        will do. `interval` is the most frames its reflection goes without
        being drawn again, and `priority` weighs it against the other mirrors
        when the frame's budget is short.'''
        far = PlanarReflector(interval=2, priority=2.0)
        silver = PBRMaterial(baseColor=surfaces.SILVER, metallic=1.0,
                             roughness=0.02, reflector=far)
        '''One reflector held by several materials tunes those mirrors
        together, and mirrors in one plane that share a reflector are drawn as
        one reflection. `varied()` makes a copy with some fields changed, for
        one mirror of a set that is worth more than the others.'''
        side = PlanarReflector(interval=3, scale=0.35)
        side_near = PBRMaterial(baseColor=surfaces.SILVER, metallic=1.0,
                                roughness=0.03, reflector=side)
        side_far = PBRMaterial(baseColor=surfaces.SILVER, metallic=1.0, roughness=0.03,
                               reflector=side.varied(interval=1, priority=3.0))
        '''A polished floor is a dielectric with a low roughness: it reflects
        faintly looking down and strongly at a glance. It covers much of the
        screen, so a low priority keeps it from crowding the wall mirrors out
        of a short budget. Any material of the procedural surfaces takes a
        reflector as well.'''
        floor = surfaces.pbr_material(surfaces.checkered_marble(256, tiles=2),
                                      reflector=PlanarReflector(interval=2, priority=0.5))
        walls = surfaces.pbr_material(surfaces.brick(256))
        '''The room itself, open to the sky: a floor, three brick walls and
        the objects the mirrors have to show, a gold column and a copper
        block. Where a mirror's view draws nothing it shows the sky.'''
        children = [
            sky_background(),
            basenodes.DirectionalLight(direction=(0.3, -1.0, -0.5), intensity=0.8),
            basenodes.PointLight(location=(0.0, 2.6, 0.0), intensity=0.8,
                                 radius=20.0),
            surfaces.shape(surfaces.panel(WIDTH, DEPTH, repeat=2.0), floor,
                           rotation=(1.0, 0.0, 0.0, -1.5708)),
            surfaces.shape(surfaces.panel(WIDTH, HEIGHT, repeat=1.5), walls,
                           translation=(0.0, HEIGHT / 2, -DEPTH / 2)),
            surfaces.shape(surfaces.panel(DEPTH, HEIGHT, repeat=1.5), walls,
                           translation=(-WIDTH / 2, HEIGHT / 2, 0.0),
                           rotation=(0.0, 1.0, 0.0, 1.5708)),
            surfaces.shape(surfaces.panel(DEPTH, HEIGHT, repeat=1.5), walls,
                           translation=(WIDTH / 2, HEIGHT / 2, 0.0),
                           rotation=(0.0, 1.0, 0.0, -1.5708)),
            surfaces.shape(surfaces.cylinder(0.3, 2.4), surfaces.pbr_material(
                surfaces.brushed_metal(128, surfaces.GOLD)),
                translation=(-2.2, 1.2, -2.0)),
            surfaces.shape(surfaces.block((0.8, 0.8, 0.8)), surfaces.pbr_material(
                surfaces.brushed_metal(128, surfaces.COPPER)),
                translation=(0.8, 0.4, 1.2)),
        ]
        '''The mirrors hang a few centimetres off their walls, so a wall
        never stands in front of the mirror on it.'''
        children += [
            surfaces.shape(surfaces.panel(4.0, 2.0), silver,
                           translation=(0.0, 1.6, -DEPTH / 2 + 0.02)),
            surfaces.shape(surfaces.panel(1.2, 1.6), side_near,
                           translation=(WIDTH / 2 - 0.02, 1.6, 1.0),
                           rotation=(0.0, 1.0, 0.0, -1.5708)),
            surfaces.shape(surfaces.panel(1.2, 1.6), side_far,
                           translation=(WIDTH / 2 - 0.02, 1.6, -2.0),
                           rotation=(0.0, 1.0, 0.0, -1.5708)),
        ]
        '''=Water is a mirror=

        Geometry with a wave style is water, and water reflects the scene
        whatever its material. A still pool sits a centimetre above the floor
        in front of the far mirror.'''
        pool = water_surface(-1.0, 3.0, -3.5, -1.5, level=0.01, resolution=17,
                             style=STILL)
        children.append(basenodes.Shape(geometry=pool, appearance=basenodes.Appearance(
            material=pool.material)))
        self.sg = basenodes.sceneGraph(children=children)
        '''=The budget=

        What a frame's reflections may cost is set on the context's
        definition: `reflectionViews` mirror views, `reflectionSeparateViews`
        of them drawing what a shared draw cannot, and `reflectionAtlas`, the
        share of the window's pixels their texture takes. The schedule spends
        it: a mirror with no reflection yet is drawn first, then those at
        their `interval`, then the rest by screen area times priority.'''
        for key in ('r', 'b', 'p'):
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(__doc__.split('Keys:')[1].strip())

    def OnKey(self, event):
        '''`r` and `b` change the definition, which the pass reads every
        frame; `p` reads the frame's `renderStats`, which is what the
        developer overlay shows.'''
        definition = self.contextDefinition
        if event.name == 'r':
            definition.planarReflections = not definition.planarReflections
            print('reflections', 'on' if definition.planarReflections else 'off')
        elif event.name == 'b':
            now = int(definition.reflectionViews or 0)
            following = BUDGETS[(BUDGETS.index(now) + 1) % len(BUDGETS)
                                if now in BUDGETS else 0]
            definition.reflectionViews = following
            print('mirror views a frame:', following or "the strategy's own")
        elif event.name == 'p':
            stats = self.renderStats
            print('%d mirror views, %d draws, %d texels, %s ms' % (
                stats.mirrorViews, stats.mirrorDraws, stats.mirrorTexels,
                stats.mirrorMilliseconds))
        self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
