#! /usr/bin/env python
'''=Physics: cloth in the wind and draped over a ball=

[physics_cloth.py-screen-0001.png Screenshot]

The yard of ``oglc-cloth``: a red banner on a bronze pole flies in a gusting
wind, a blue cloth falls over a sandstone ball and settles on it, and a
canvas sheet hangs from a wooden beam with its lower corners pinned.  Each is
a mesh the physics service simulates as a soft body: ``add_soft_mesh`` welds
the mesh's vertices into particles, and every frame the cloth moves the
service writes them back into the mesh's vertex buffer.

The script opens on two seconds already played.  The keys the demo prints
drop the drape again, change the wind, release the sheet and throw a ball
at it.
'''
from OpenGLContext.bin.cloth_demo import ClothYard, definition
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.contextdefinition import ContextDefinition

#: How much is played before the first frame, in seconds, in steps of what length.
OPENING = 2.0
STEP = 1.0 / 60.0


class TestContext(BaseContext):
    '''The world steps in the frame (``definition()``), so the opening is the
    same on every run.'''
    renderer = 'pbr'
    initialPosition = (0.0, 2.2, 6.5)
    initialOrientation = (-1, 0, 0, 0.12)
    contextDefinition = ContextDefinition(physics=definition())

    def OnInit(self):
        '''The yard's ``_banner``, ``_drape`` and ``_sheet`` make the three
        cloths.  Each is ``physics.add_soft_mesh(mesh, position, rotation,
        pins=(vertices, points), mass=...)``: the banner pinned along the
        pole, the drape free above the ball, the sheet by its corners.'''
        self.yard = ClothYard(self.physics)
        self.sg = self.yard.scene()
        '''The wind is a force on each body, set every frame by
        ``soft.set_wind(force)`` in the yard's ``update``.'''
        self.animate(self.yard.update)
        '''A handler is held by weak reference, so a lambda made on the spot
        would be gone before the first key. The keys share ``OnKey``, a
        method of the context, which looks the action up by the key's name.'''
        self.keys = {'d': self.yard.drop, 'w': self.yard.next_wind,
                     'r': self.yard.toggle_sheet, ' ': self.yard.throw}
        for key in self.keys:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        for _ in range(round(OPENING / STEP)):
            self.yard.update(STEP)
            self.physics.frame(STEP)
        print(__doc__)

    def OnKey(self, event):
        self.keys[event.name]()


if __name__ == '__main__':
    TestContext.ContextMainLoop()
