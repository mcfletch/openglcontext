#!/usr/bin/env python
"""Interactive context using the PyGame API (provides navigation support)"""
from OpenGLContext.pygamecontext import *
from OpenGLContext import interactivecontext
from OpenGLContext.move import viewplatformmixin


class PygameInteractiveContext(
    viewplatformmixin.ViewPlatformMixin,
    interactivecontext.InteractiveContext,
    PygameContext,
):
    '''PyGame context providing mouse and keyboard interaction '''
    def PygameActivateEvent(self, event):
        return 1
    def OnIdle(self, *arguments):
        """Animation hook for the pygame loop.

        The default Context.OnIdle renders via drawPoll, which would double up
        with MainLoop's own OnDraw. Demos that animate override this to call
        triggerRedraw; the base behaviour here is to do nothing and let
        MainLoop drive rendering.
        """
        return 0

    
if __name__ == '__main__':
    from drawcube import drawCube
    class TestContext(PygameInteractiveContext):
        def Render(self, mode):
            glTranslated(0, 0, -3)
            glRotated(30, 1, 0, 0)
            glRotated(30, 0, 1, 0)
            drawCube()
    TestContext.ContextMainLoop(
        title='Interactive Pygame Context', size=(400,300)
    )
    
