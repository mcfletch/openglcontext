#! /usr/bin/env python
"""Right-drag a scene through a real GL context and report what the camera did.

Run as a subprocess by ``tests/unit/test_examine_drag_gl.py``.  Everything a
right-drag passes through is real here -- the selection pass that decides what
was clicked, the pivot the context chooses from it, the orbit and the view
platform -- because the point of the exercise is that the *whole* chain leaves
the object on screen.

Usage:  _examine_drive.py <startX> <startY> <dragX> <dragY>

Coordinates are pick points: pixels from the bottom left, y counting upward.
Prints, one per line:

``PIVOT``     the world point the drag orbited
``DISTANCE``  camera-to-model-centre before and after
``PIXEL``     where the model's centre is drawn, after
``LEVEL``     the camera's up axis dotted with the world's
``ONSCREEN``  whether the model's centre is still inside the window
"""
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
os.environ.setdefault('OPENGLCONTEXT_NO_VSYNC', '1')
os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '90')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

import numpy as np                                          # noqa: E402
from OpenGL.GLU import gluProject                           # noqa: E402

from OpenGLContext import testingcontext                    # noqa: E402
from OpenGLContext.events import synthetic                  # noqa: E402
from OpenGLContext.scenegraph.basenodes import (            # noqa: E402
    Box, Shape, Transform, sceneGraph,
)

BaseContext = testingcontext.getInteractive()

START = (int(sys.argv[1]), int(sys.argv[2]))
DRAG = (int(sys.argv[3]), int(sys.argv[4]))

#: How many frames a step may wait for the pick to answer before giving up.
PATIENCE = 20

#: How many movements the drag is delivered in.  A real drag is a stream of
#: them, and a gesture that is right only for a single jump is not right.
STEPS = 6


class DriverContext(BaseContext):
    """A box on screen, and a hand on the right mouse button."""

    initialPosition = (0.0, 0.0, 10.0)
    _waited = 0

    def OnInit(self):
        self.sg = sceneGraph(children=[
            Transform(children=[Shape(geometry=Box(size=(2, 2, 2)))]),
        ])
        self.script = [self._press, self._drag, self._report]
        self._before = None

    def getSceneGraph(self):
        return self.sg

    def OnIdle(self, *arguments):
        if not self.script:
            return 0
        if self.script[0]():
            self.script.pop(0)
            self._waited = 0
        else:
            self._waited += 1
            if self._waited > PATIENCE:
                print('GAVE UP', flush=True)
                self.OnQuit()
        self.triggerRedraw(1)
        return 0

    ### helpers
    def _pixel(self, point):
        """Where a world point is drawn, in pick-point pixels"""
        width, height = self.getViewPort()
        return gluProject(
            point[0], point[1], point[2],
            np.asarray(self.platform.modelMatrix(), 'd'),
            np.asarray(self.platform.viewMatrix(), 'd'),
            np.asarray((0, 0, width, height), 'i'),
        )[:2]

    def _post(self, *records):
        for record in records:
            event = synthetic.build(record)
            event.context = self
            self.addPickEvent(event)
        self.triggerPick()

    ### the steps
    def _press(self):
        self._before = np.asarray(self.platform.position, 'd')[:3].copy()
        self._post({'type': 'mousebutton', 'button': 1, 'state': 1,
                    'x': START[0], 'y': START[1]})
        return True

    def _drag(self):
        if not self.isCapturingEvents('mousemove'):
            return False                    # the examine mode has not begun
        self._pivotPoint = np.asarray(self._pivot(), 'd')
        print('PIVOT %s' % (' '.join('%.6f' % value
                                     for value in self._pivotPoint),), flush=True)
        for step in range(1, STEPS + 1):
            self._post({'type': 'mousemove', 'buttons': [1],
                        'x': START[0] + DRAG[0] * step // STEPS,
                        'y': START[1] + DRAG[1] * step // STEPS})
        self._post({'type': 'mousebutton', 'button': 1, 'state': 0,
                    'x': START[0] + DRAG[0], 'y': START[1] + DRAG[1]})
        return True

    def _pivot(self):
        """The point the live gesture is orbiting.

        A capture *replaces* the manager in the dispatch slot, so the examine
        manager is what the context now answers with for mouse movement.
        """
        orbit = getattr(self.getEventManager('mousemove'), 'orbit', None)
        if orbit is None:
            return (float('nan'),) * 3
        return tuple(float(value) for value in orbit.centre[:3])

    def _report(self):
        # Pick readback is asynchronous -- the selection pass asks the GPU what
        # is under the cursor and dispatches a frame or more later -- so the
        # drag has to be waited for rather than assumed delivered.
        self.flushPendingPicks()
        if self.isCapturingEvents('mousemove'):
            return False                    # the release has not arrived yet
        position = np.asarray(self.platform.position, 'd')[:3]
        pivot = self._pivotPoint
        width, height = self.getViewPort()
        x, y = self._pixel((0.0, 0.0, 0.0))
        up = np.asarray(self.platform.quaternion * np.array([0.0, 1.0, 0.0, 0.0]),
                        dtype='d')[:3]
        right = np.asarray(self.platform.quaternion
                           * np.array([1.0, 0.0, 0.0, 0.0]), dtype='d')[:3]
        print('ROLL %.6f' % (float(np.dot(right, [0.0, 1.0, 0.0])),), flush=True)
        print('DISTANCE %.6f %.6f' % (
            float(np.linalg.norm(self._before - pivot)),
            float(np.linalg.norm(position - pivot))), flush=True)
        print('SWING %.4f' % (_angle(self._before - pivot, position - pivot),),
              flush=True)
        print('PIXEL %.2f %.2f  OF %d %d' % (x, y, width, height), flush=True)
        print('LEVEL %.6f' % (float(np.dot(up, [0.0, 1.0, 0.0])),), flush=True)
        print('ONSCREEN %s' % (0 <= x <= width and 0 <= y <= height,), flush=True)
        print('DONE', flush=True)
        self.OnQuit()
        return True


def _angle(first, second):
    """The angle in degrees between two vectors"""
    first = np.asarray(first, 'd') / max(float(np.linalg.norm(first)), 1e-12)
    second = np.asarray(second, 'd') / max(float(np.linalg.norm(second)), 1e-12)
    return float(np.degrees(np.arccos(np.clip(np.dot(first, second), -1.0, 1.0))))


if __name__ == '__main__':
    DriverContext.ContextMainLoop(size=(400, 300))
