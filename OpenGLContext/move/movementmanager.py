"""Interactions for navigating the context"""

from gettext import gettext as _
import logging

log = logging.getLogger(__name__)


class MovementManager(object):
    """Base class for movement interaction controllers"""

    commands = [
        # User-name, key, function-name
        (_("Examine"), "examine", "startExamineMode"),
        (_("Pan"), "pan", "startPanMode"),
        (_("Zoom In"), "zoomin", "zoomIn"),
        (_("Zoom Out"), "zoomout", "zoomOut"),
    ]
    commandBindings = dict(
        # key : { addEventHandler parameters }
    )
    context = None

    def __init__(self, platform):
        """Initialize direct movement with the platform it controls"""
        self.platform = platform

    def bind(self, context):
        """Bind this navigation mechanism to the context"""
        self.context = context
        log.info("Binding %r movement manager", self)
        for title, key, function in self.commands:
            binding = self.commandBindings.get(key)
            if binding is not None:
                func = getattr(self, function, None)
                if func is not None:
                    log.info("Movement binding: %s, %s", func, binding)
                    context.addEventHandler(function=func, **binding)
                else:
                    log.warning(
                        "No method %s registered as handler for %s on %s",
                        function,
                        key,
                        self.__class__.__name__,
                    )

    def unbind(self, context):
        """Unbind this navigation mechanism from the context"""
        log.info("Unbinding %r movement manager", self)
        for title, key, function in self.commands:
            binding = self.commandBindings.get(key)
            if binding is not None:
                func = None
                context.addEventHandler(function=func, **binding)
        self.context = None

    def startExamineMode(self, event):
        """(callback) Orbit the view about what the pointer is on

        This callback creates an instance of
        examinemanager.ExamineManager, which will manage
        the user interaction during an "examination" of
        the scene.
        """
        return self._startGesture(event)

    def startPanMode(self, event):
        """(callback) Carry the scene across the view with the pointer"""
        from OpenGLContext.move import examinemanager

        return self._startGesture(event, gesture=examinemanager.PAN)

    def _startGesture(self, event, gesture=None):
        """Begin one examine gesture about the point the pointer is on"""
        from OpenGLContext.move import examinemanager

        # The context decides where the pivot is: it is what knows how big the
        # scene is and where the camera is standing in it.  A pivot chosen
        # without that makes the drag swing about a point that has nothing to
        # do with what is on screen.
        center = self.context.examineCenter(event)
        return examinemanager.ExamineManager(
            self.context,
            self.platform,
            center,
            event,
            gesture=gesture or examinemanager.ROTATE,
        )

    def zoomIn(self, event):
        """(callback) Move one wheel notch toward what is being looked at"""
        from OpenGLContext.move import examinemanager

        return self._dolly(event, examinemanager.DOLLY_STEP)

    def zoomOut(self, event):
        """(callback) Move one wheel notch away from what is being looked at"""
        from OpenGLContext.move import examinemanager

        return self._dolly(event, 1.0 / examinemanager.DOLLY_STEP)

    def _dolly(self, event, factor):
        """Move the camera along the line to the pivot, keeping its aim

        The same pivot an examine drag would use, so scrolling and dragging
        agree about what is being looked at.
        """
        from OpenGLContext.move import examinemanager

        width, height = self.context.getViewPort()
        gesture = examinemanager.orbitFor(
            self.platform, self.context.examineCenter(event), event,
            width, height,
        )
        position, orientation = gesture.dolly(factor)
        self.platform.position = position
        self.platform.quaternion = orientation
        self.context.triggerRedraw(1)
