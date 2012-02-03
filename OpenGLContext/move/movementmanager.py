"""Interactions for navigating the context"""
from gettext import gettext as _
from OpenGLContext import quaternion
import logging 
log = logging.getLogger( __name__ )

class MovementManager( object ):
    """Base class for movement interaction controllers"""
    commands = [
        # User-name, key, function-name
        (_('Examine'), 'examine', 'startExamineMode' ),
    ]
    commandBindings = dict(
        # key : { addEventHandler parameters } 
    )
    context = None
    def __init__( self, platform ):
        """Initialize direct movement with the platform it controls"""
        self.platform = platform
    def bind( self, context ):
        """Bind this navigation mechanism to the context"""
        self.context = context
        log.info( "Binding %r movement manager", self )
        for (title,key,function) in self.commands:
            binding = self.commandBindings.get( key )
            if binding is not None:
                func = getattr( self, function, None )
                if func is not None:
                    log.info( 'Movement binding: %s, %s', func, binding )
                    context.addEventHandler(function=func,**binding)
                else:
                    log.warn( 'No method %s registered as handler for %s on %s', 
                        function, key, self.__class__.__name__,
                    )
    def unbind( self, context ):
        """Unbind this navigation mechanism from the context"""
        log.info( "Unbinding %r movement manager", self )
        for (title,key,function) in self.commands:
            binding = self.commandBindings.get( key )
            if binding is not None:
                func = None
                context.addEventHandler(function=func,**binding)
        self.context = None
    def startExamineMode (self, event):
        """(callback) Create an examine mode interaction manager

        This callback creates an instance of
        examinemanager.ExamineManager, which will manage
        the user interaction during an "examination" of
        the scene.
        """
        from OpenGLContext.move import examinemanager
        try:
            center = event.unproject()
        except ValueError:
            center = self.platform.quaternion * [0,0,-10,0] + self.platform.position
        examinemanager.ExamineManager(
            self.context, self.platform, center,event,
        )
