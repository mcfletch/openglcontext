#! /usr/bin/env python
"""Drive ``tests/tutorials/scenegraph/molehill_edit.py`` through a real pick, and report what moved.

Run as a subprocess by ``tests/unit/test_molehill_edit_drag.py``.  It selects a
control point, grabs one arm of the gizmo, drags it a set distance along that
arm and prints what came of it, so the whole chain -- the selection pass, the
node path it resolves, the axis-constrained drag and the write back into the
NURBS surface -- is exercised in a real GL context rather than mocked.

The steps run one per frame from ``OnIdle``, each waiting for the pick to answer
the step before it, so nothing here depends on wall-clock timing.  Pick
readback is asynchronous and lands however many frames the GPU takes, so a
step that waits on a pick delivers the picks in flight before it looks.

Usage:  _molehill_edit_driver.py <net> <point> <axis> <distance> [behind]

``behind`` runs the drag on a GPU that has not finished any frame's readback
by the frame after it: the selection pass's non-blocking drain finds no fence
signalled, as on a loaded machine.
"""
import os
import sys

os.environ.setdefault('OPENGLCONTEXT_BACKEND', 'glfw')
os.environ.setdefault('OPENGLCONTEXT_HIDDEN', '1')
os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '60')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

import types
from typing import Any

import numpy as np

from OpenGLContext.events.mouseevents import projected
from OpenGLContext.edit.gizmo import AXES
from OpenGLContext.events import synthetic
from OpenGLContext.scenegraph.nodepath import NodePath
from OpenGLContext.testing.paths import tests_root

sys.path.insert(0, str(tests_root(__file__) / 'tutorials' / 'scenegraph'))
from molehill_edit import TestContext as BaseContext

NET, POINT, AXIS = (int(value) for value in sys.argv[1:4])
DISTANCE = float(sys.argv[4])
BEHIND = sys.argv[5:6] == ['behind']

#: How many frames a step may wait for the pick before the run is called off.
PATIENCE = 15

#: Where along the arm to take hold of it, as a fraction of its length. The
#: arms meet at the point they stand on, so near the root they overlap on
#: screen and which one a pixel belongs to depends on the angle; out at the
#: arrowhead they have separated and the aim is unambiguous from anywhere.
GRAB_AT = 0.85


class DriverContext(BaseContext):
    """The editing demo, with a hand on its mouse."""

    def OnInit(self) -> None:
        super(DriverContext, self).OnInit()
        self.script = [self._select, self._grab, self._drag, self._report]
        self._waited = 0
        self._started: np.ndarray = np.zeros(3)

    def _pixel(self, point: Any) -> tuple[float, float]:
        """Where a point in the scene group's coordinates is drawn, in pixels.

        The scene is scaled and turned before it is drawn, so a control point's
        own coordinates have to go through that transform before the projection
        can say which pixel to aim at.
        """
        matrix = NodePath([self.sg, self.sg.children[0]]).transformMatrix()
        root = np.dot(np.append(np.asarray(point, 'd'), 1.0), matrix)[:3]
        width, height = self.getViewPort()
        view = types.SimpleNamespace(
            modelViewMatrix=self.platform.modelMatrix(),
            projectionMatrix=self.platform.viewMatrix(),
            viewport=(0, 0, width, height))
        return tuple(projected(view, root)[:2])

    def _post(self, *records: dict[str, Any]) -> None:
        for record in records:
            event = synthetic.build(record)
            assert event is not None, record
            event.context = self
            self.addPickEvent(event)
        self.triggerPick()

    # -- the steps ---------------------------------------------------------
    def _select(self) -> bool:
        x, y = self._pixel(self.nets[NET].point(POINT))
        self._post({'type': 'mousebutton', 'button': 0, 'state': 1,
                    'x': x, 'y': y},
                   {'type': 'mousebutton', 'button': 0, 'state': 0,
                    'x': x, 'y': y})
        return True

    def _grab(self) -> bool:
        if self.selection is None:
            return False
        print('SELECTED %d' % (self.selection[1],), flush=True)
        self._started = self.nets[NET].point(POINT).copy()
        along = np.asarray(AXES[AXIS], 'd') * self.GIZMO_SIZE * GRAB_AT
        x, y = self._pixel(self.gizmo.position + along)
        self._post({'type': 'mousebutton', 'button': 0, 'state': 1,
                    'x': x, 'y': y})
        return True

    def _drag(self) -> bool:
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

    def _report(self) -> bool:
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

    def OnIdle(self, *arguments: Any) -> int:
        if self.script:
            # The last frame's picks resolve when the GPU finishes them, which
            # a busy machine puts any number of frames off; deliver them now so
            # the step reads the answer to the step before it.
            self.flushPendingPicks()
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


def _drain_none(self: Any, mode: Any) -> None:
    """Deliver nothing, as on a GPU whose readback fences have not signalled."""
    if self._async_batches:
        self._askForDelivery(mode)


if __name__ == "__main__":
    if BEHIND:
        from OpenGLContext.passes.asyncpick import _AsyncPickMixin
        _AsyncPickMixin.drainAsyncPicks = _drain_none  # type: ignore[method-assign]  # the slow GPU is this run's subject
    DriverContext.ContextMainLoop()
