#! /usr/bin/env python
'''=Zones: rooms lit as rooms=

[zones_demo.py-screen-0001.png Screenshot]

The court of ``oglc-zones``: a marble courtyard under the sky, and two roofed
rooms off it.  Nothing in either room is lit differently by its material or
its geometry; each room is a ``Zone``, and the zone's settings decide how what
is inside it is lit.

The west room's zone scales the sky's light down to the share a roofed room
gets and names the warm lamp hanging in it.  The east room's zone captures a
probe from its own centre, so it is lit by what can be seen from in there, and
names a cool lamp.  Each lamp lights its own room and nothing in the
courtyard, although nothing stands between the east lamp and the fountain but
an open door.
'''
import os

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()

from OpenGLContext.bin.zones_demo import ZoneCourt
from OpenGLContext.scenegraph.basenodes import sceneGraph


class TestContext(BaseContext):
    initialPosition = (0.0, 1.8, 8.0)

    def OnInit(self):
        '''The court builds the scene, the lamps and the zones.  Its ``_room``
        is where a zone is made: a ``Zone`` the size of the room, placed by the
        ``Transform`` above it, with ``ZoneLights(lights=[lamp])`` and a
        ``ZoneEnvironment``, ``intensity=0.15`` for the west room and
        ``capture=True`` for the east.  The lamps themselves stand in the scene
        like any other light; a zone names them.'''
        self.court = ZoneCourt()
        self.sg = sceneGraph(children=self.court.children)
        '''``z`` takes the rooms' zones out of the scene and puts them back:
        without them the sky lights both rooms as it lights the courtyard, and
        each lamp lights whatever it reaches.  ``t`` shows the gold statue in
        the east room from everywhere, rather than only from inside that room,
        which a ``ZoneVisibility`` in a zone covering the whole court, and
        another in the room at a higher priority, arrange between them.'''
        for key in ZoneCourt.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(ZoneCourt.help())

    def OnKey(self, event):
        said = self.court.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
