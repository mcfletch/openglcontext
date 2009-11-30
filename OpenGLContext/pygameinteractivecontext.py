#!/usr/bin/env python
"""Interactive context using the PyGame API (provides navigation support)"""

import string

from OpenGLContext.pygamecontext import *
from OpenGLContext import interactivecontext
from OpenGLContext.move import viewplatformmixin


class PygameInteractiveContext(
    viewplatformmixin.ViewPlatformMixin,
    interactivecontext.InteractiveContext,
    PygameContext,
):
    '''PyGame context providing mouse and keyboard interaction '''
    def PygameVideoResize(self, event):
        sizex, sizey = event.size
        PygameContext.PygameVideoResize(self, event)
        self.CallVirtual('OnResize', sizex, sizey)
        return 1
    def PygameActivateEvent(self, event):
        return 1
    def OnIdle(self): 
        pass

    
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
    