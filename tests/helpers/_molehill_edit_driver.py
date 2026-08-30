#! /usr/bin/env python
"""Drive ``tests/molehill_edit.py`` through a real pick, and report what moved.

Run as a subprocess by ``tests/unit/test_molehill_edit_drag.py``.  It selects a
control point, grabs one arm of the gizmo, drags it a set distance along that
arm and prints what came of it, so the whole chain -- the selection pass, the
node path it resolves, the axis-constrained drag and the write back into the
NURBS surface -- is exercised in a real GL context rather than mocked.

The steps run one per frame from ``OnIdle``, each waiting for the pick to answer
the step before it, so nothing here depends on wall-clock timing.

Usage:  _molehill_edit_driver.py <net> <point> <axis> <distance>
"""
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '60')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

import numpy as np
from OpenGL.GLU import gluProject

from OpenGLContext.edit.gizmo import AXES
from OpenGLContext.events import synthetic
from OpenGLContext.scenegraph.nodepath import NodePath
from OpenGLContext.testing.paths import tests_root

sys.path.insert(0, str(tests_root(__file__)))
from molehill_edit import TestContext as BaseContext     # noqa: E402

NET, POINT, AXIS = (int(value) for value in sys.argv[1:4])
DISTANCE = float(sys.argv[4])

#: How many frames a step may wait for the pick before the run is called off.
PATIENCE = 15

#: Where along the arm to take hold of it, as a fraction of its length. The
#: arms meet at the point they stand on, so near the root they overlap on
#: screen and which one a pixel belongs to depends on the angle; out at the
#: arrowhead they have separated and the aim is unambiguous from anywhere.
GRAB_AT = 0.85


class DriverContext(BaseContext):
    """The editing demo, with a hand on its mouse."""

    def OnInit(self):
        super(DriverContext, self).OnInit()
        self.script = [self._select, self._grab, self._drag, self._report]
        self._waited = 0
        self._started = None

    def _pixel(self, point):
        """Where a point in the scene group's coordinates is drawn, in pixels.

        The scene is scaled and turned before it is drawn, so a control point's
        own coordinates have to go through that transform before the projection
        can say which pixel to aim at.
        """
        matrix = NodePath([self.sg, self.sg.children[0]]).transformMatrix()
        root = np.dot(np.append(np.asarray(point, 'd'), 1.0), matrix)[:3]
        width, height = self.getViewPort()
        return gluProject(
            root[0], root[1], root[2],
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

    # -- the steps ---------------------------------------------------------
    def _select(self):
        x, y = self._pixel(self.nets[NET].point(POINT))
        self._post({'type': 'mousebutton', 'button': 0, 'state': 1,
                    'x': x, 'y': y},
                   {'type': 'mousebutton', 'button': 0, 'state': 0,
                    'x': x, 'y': y})
        return True

    def _grab(self):
        if self.selection is None:
            return False
        print('SELECTED %d' % (self.selection[1],), flush=True)
        self._started = self.nets[NET].point(POINT).copy()
        along = np.asarray(AXES[AXIS], 'd') * self.GIZMO_SIZE * GRAB_AT
        x, y = self._pixel(self.gizmo.position + along)
        self._post({'type': 'mousebutton', 'button': 0, 'state': 1,
                    'x': x, 'y': y})
        return True

    def _drag(self):
        if self.gizmo.dragging is None:
            return False
        print('GRABBED %d' % (self.gizmo.dragging,), flush=True)
        along = np.asarray(AXES[AXIS], 'd') * (self.GIZMO_SIZE * GRAB_AT
                                              + DISTANCE)
        x, y = self._pixel(self.gizmo.position + along)
        self._post({'type': 'mousemove', 'buttons': [0], 'x': x, 'y': y},
                   {'type': 'mousebutton', 'button': 0, 'state': 0,
                    'x': x, 'y': y})
        return True

    def _report(self):
        moved = self.nets[NET].point(POINT)
        if np.allclose(moved, self._started):
            return False
        print('MOVED %s' % (' '.join('%.6f' % value
                                     for value in moved - self._started),),
              flush=True)
        print('SURFACE %s' % (' '.join(
            '%.6f' % value
            for value in self.nets[NET].surface.controlPoint[POINT]),),
            flush=True)
        print('RELEASED %s' % (self.gizmo.dragging is None,), flush=True)
        print('DONE', flush=True)
        return True

    def OnIdle(self, *arguments):
        if self.script:
            if self.script[0]():
                self.script.pop(0)
                self._waited = 0
            else:
                self._waited += 1
                if self._waited > PATIENCE:
                    print('GAVE UP AT %s' % (self.script[0].__name__,),
                          flush=True)
                    self.script = []
            self.triggerRedraw(1)
        return 0


if __name__ == "__main__":
    DriverContext.ContextMainLoop()
