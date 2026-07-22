#! /usr/bin/env python
"""Interactive target driven by the event-injection subsystem.

Launched as a subprocess with ``--event-socket PATH`` by the interactive_runner
fixture. It binds a real ``mousebutton`` handler and pumps injected events from
its OnIdle loop, so an injected click flows all the way through the IPC socket,
EventInjector, and the OpenGLContext event manager to application code. When the
click is dispatched the handler prints a unique marker line the test asserts on.

Usage:  python tests/helpers/interactive_click_target.py --event-socket PATH
"""
import os

# Render effectively forever: the injected 'exit' event ends the run, with the
# interactive_runner's timeout + process-tree kill as the backstop. A small frame
# cap would auto-exit before the click is injected.
os.environ.setdefault('OPENGLCONTEXT_AUTO_EXIT_FRAMES', '1000000')
os.environ['OPENGLCONTEXT_DISABLE_FPS_DISPLAY'] = '1'

from OpenGLContext import testingcontext
from OpenGLContext.testing.event_injector import EventInjectionMixin

BaseContext = testingcontext.getInteractive()

CLICK_MARKER = "INJECTED_CLICK_DISPATCHED"


class InteractiveClickTarget(EventInjectionMixin, BaseContext):
    def OnInit(self):
        self.setup_event_injection()
        self.addEventHandler(
            "mousebutton", button=0, state=1, function=self.OnClick
        )

    def OnClick(self, event=None):
        # Reaching here proves the injected event traversed socket -> injector
        # -> event manager -> handler. Flush so the parent sees it promptly.
        print(CLICK_MARKER, flush=True)

    def OnIdle(self, *args):
        self.poll_injected_events()
        self.triggerRedraw(1)


if __name__ == "__main__":
    InteractiveClickTarget.ContextMainLoop()
