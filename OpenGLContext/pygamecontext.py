#!/usr/bin/env python
'''Context functionality within the PyGame environment
'''

#test and import pygame
try:
    import pygame
    from pygame.locals import *
    import pygame.key
    import pygame.display
except ImportError:
    raise ImportError, "The pygame package is required for the Pygame GL Context"
if pygame.ver < '1.1':
    raise ImportError, "Pygame v1.1 or greater is required for the Pygame GL Context"

#import opengl stuff
from OpenGL.GL import *
from OpenGLContext.context import Context
from OpenGLContext.events import pygameevents
import logging 
log = logging.getLogger( __name__ )
from OpenGLContext import contextdefinition

class PygameContext(
    pygameevents.EventHandlerMixin,
    Context,
):
    """Context sub-class providing basic API support under PyGame

    Unlike most of the windowing APIs, PyGame requires you to write
    an explicit event handler loop, we provide a default loop method
    called MainLoop.
    """
    def __init__(self, definition=None, **named):
        #init pygame
        pygame.display.init()
        if definition is None:
            definition = contextdefinition.ContextDefinition( **named )
        else:
            for key,value in named.items():
                setattr( definition, key, value )
        self.contextDefinition = definition
        self.screen = self.pygameDisplayMode( definition )
        pygame.display.set_caption(definition.title or self.getApplicationName())
        pygame.key.set_repeat(500,30)
        Context.__init__ (self, definition)
        self.ViewPort(*definition.size)

    def pygameFlagsFromDefinition( cls, definition ):
        """Setup the various non-initialising flags, return init flags"""
        set = pygame.display.gl_set_attribute
        if definition.depthBuffer > -1:
            set( GL_DEPTH_SIZE, definition.depthBuffer )
        if definition.stencilBuffer > -1:
            set( GL_STENCIL_SIZE, definition.stencilBuffer )
        if definition.accumulationBuffer > -1:
            set( GL_ACCUM_ALPHA_SIZE, definition.accumulationBuffer )
            set( GL_ACCUM_RED_SIZE, definition.accumulationBuffer )
            set( GL_ACCUM_GREEN_SIZE, definition.accumulationBuffer )
            set( GL_ACCUM_BLUE_SIZE, definition.accumulationBuffer )
        if definition.multisampleBuffer > -1 and definition.multisampleSamples > -1:
            set( GL_MULTISAMPLEBUFFERS, definition.multisampleBuffer )
            set( GL_MULTISAMPLESAMPLES, definition.multisampleSamples )
        if definition.stereo > -1:
            set( GL_STEREO, definition.stereo )
        if definition.doubleBuffer:
            return DOUBLEBUF|RESIZABLE
        else:
            return RESIZABLE
    pygameFlagsFromDefinition = classmethod( pygameFlagsFromDefinition )
    def pygameDisplayMode( self, definition=None ):
        if definition is None:
            definition = self.contextDefinition
        self.screen = pygame.display.set_mode(
            tuple([int(i) for i in definition.size]),
            OPENGL | self.pygameFlagsFromDefinition( definition ),
        )
        return self.screen
    def CallVirtual(self, name, *args, **namedarguments):
        "Call a potentially undefined method"
        func = getattr(self, name, lambda *x, **y:1)
        return func( *args, **namedarguments)


    def SwapBuffers (self):
        "flip opengl doublebuffers"
        pygame.display.flip()


    def MainLoop( self ):
        """Run indefinitely until program is quit"""
        finished = 0
        renderedFirst = 0
        counter = range( 100 )
        while not finished:
            #draw if needed, else delay a bit
            timeout = self.drawPollTimeout
            self.redrawRequest.wait( timeout )
            if self.redrawRequest.isSet() or (not renderedFirst):
                renderedFirst = 1
                self.OnDraw( force = 1)
            else:
                self.OnDraw( force = 0)
            #loop through all pending events
            for count in counter:
                event = pygame.event.poll()
                if not event.type:
                    self.OnIdle()
                name = 'Pygame' + pygame.event.event_name(event.type)
                if not self.CallVirtual(name, event):
                    finished = 1
                    break
                if event.type in ( pygame.VIDEORESIZE, pygame.VIDEOEXPOSE):
                    self.triggerRedraw( 0 )
                    break

    def PygameQuit(self, event):
        """Return a value indicating that the MainLoop should exit"""
        return 0

    def PygameVideoResize(self, event):
        """Handle the resize of the window"""
        sizex, sizey = self.contextDefinition.size = event.size
        self.ViewPort(sizex, sizey)
        self.pygameDisplayMode()
        self.triggerRedraw(1)
        return 1

    def ContextMainLoop( cls, *args, **named ):
        """Initialise the context and start the mainloop"""
        instance = cls( *args, **named )
        if instance.contextDefinition.profileFile:
            # profiling run...
            import cProfile
            return cProfile.runctx(
                "instance.MainLoop()",
                globals(),
                locals(),
                instance.contextDefinition.profileFile
            )
        return instance.MainLoop()
    ContextMainLoop = classmethod( ContextMainLoop )


if __name__ == '__main__':
    from drawcube import drawCube
    class TestContext(PygameContext):
        def Render(self, mode):
            glTranslated(0, 0, -3)
            glRotated(30, 1, 0, 0)
            glRotated(40, 0, 1, 0)
            drawCube()
    TestContext.ContextMainLoop()
