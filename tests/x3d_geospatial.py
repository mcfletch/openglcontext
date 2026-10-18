#! /usr/bin/env python
'''=X3D: an alpine valley placed on the Earth=

[x3d_geospatial.py-screen-0001.png Screenshot]

``x3d_geospatial.x3d`` is an X3D 4 document whose content is placed by
latitude, longitude and height rather than by metres from an origin:

* the valley is a ``GeoElevationGrid`` stepping ``xSpacing`` degrees of
  longitude across and ``zSpacing`` degrees of latitude deep; its heights are
  metres above the WGS84 ellipsoid;
* a ``GeoLOD`` draws that coarse grid from afar and, within two and a half
  kilometres of its ``center``, four finer tiles read from their own files;
* each hut is a ``GeoLocation``: its children are drawn in the frame at its
  ``geoCoords``, up along the ellipsoid's normal and -Z north;
* the balloon's loop is a ``GeoPositionInterpolator``, which moves along the
  globe between its keys and sends the place in the scene's coordinates;
* the three ``GeoViewpoint`` nodes look across it, one given in UTM;
* a ``GeoProximitySensor`` reports where the viewer is, and a
  ``GeoTouchSensor`` where the ground is clicked.

Every node names the same ``GeoOrigin``, whose ``rotateYUp`` turns the
scene so the valley's up is +Y; the coordinates are worked out in double
precision, so the huts stand on the ground to the millimetre.

The arrow keys fly the camera. A ``GeoViewpoint`` scales navigation by a
tenth of the viewer's height above the ellipsoid, in metres, times its
``speedFactor``; the document's 0.1 makes a key press a step of two and a
half metres among the huts and eight from the highest viewpoint. ``]``
lengthens the step by half and ``[`` shortens it.
'''
import os
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_geospatial_demo import Showcase
from OpenGLContext.loaders import background
from pydispatch import dispatcher
from vrml import protofunctions


class TestContext(BaseContext):

    def OnInit(self):
        '''The showcase writes the document, its four tiles and the maps they
        name, and reads it with ``Loader.load``.'''
        self.showcase = Showcase(tempfile.mkdtemp(prefix='x3d-geospatial-'))
        background.wait_for_idle(20.0)
        self.sg = self.showcase.scene
        '''``g`` prints where the viewer is in latitude, longitude and height,
        and ``w`` writes the scene back as X3D in each encoding.'''
        for key in Showcase.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(Showcase.help())
        '''A click on the ground sets the ``GeoTouchSensor``'s ``touchTime``,
        and its ``hitGeoCoord_changed`` is then where the click landed.'''
        touch = self.sg.getDEF('Touch')
        dispatcher.connect(
            self.OnTouch, sender=touch,
            signal=('set', protofunctions.getField(touch, 'touchTime')))

    def OnKey(self, event):
        said = self.showcase.press(event.name)
        if said:
            print(said)
            self.triggerRedraw(True)

    def OnTouch(self, **named):
        said = self.showcase.said_of_touch()
        if said:
            print(said)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
