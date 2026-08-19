#! /usr/bin/env python
"""Interactive target that renders only when something changed.

Most applications are like this -- an editor, a model viewer, a map -- and it is
the case a pick has to survive: the event is read back from the selection buffer
during a *later* render, and there is nothing to draw while it is in flight.
Launched as a subprocess with ``--event-socket PATH``; prints a marker when a
picked click reaches the handler.

Usage:  python tests/helpers/ondemand_click_target.py --event-socket PATH
"""
import os

# Render effectively forever: the injected 'exit' event ends the run.
os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '1000000')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

from OpenGLContext import testingcontext
from OpenGLContext.scenegraph.basenodes import (
    Appearance, Box, Material, Shape, sceneGraph,
)
from OpenGLContext.testing.event_injector import EventInjectionMixin

BaseContext = testingcontext.getInteractive()

CLICK_MARKER = "PICKED_CLICK_DISPATCHED"


class OnDemandClickTarget(EventInjectionMixin, BaseContext):
    def OnInit(self):
        self.setup_event_injection()
        self.sg = sceneGraph(children=[
            Shape(geometry=Box(size=(4, 4, 4)),
                  appearance=Appearance(material=Material(
                      diffuseColor=(0.7, 0.2, 0.2)))),
        ])
        self.addEventHandler(
            "mousebutton", button=0, state=1, function=self.OnClick
        )

    def OnClick(self, event=None):
        print(CLICK_MARKER, flush=True)

    def OnIdle(self, *args):
        # Deliberately no triggerRedraw: nothing here animates, so the loop
        # renders only when the application or the pass asks it to.
        self.poll_injected_events()


if __name__ == "__main__":
    OnDemandClickTarget.ContextMainLoop()
