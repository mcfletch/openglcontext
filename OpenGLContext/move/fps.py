"""First-person-shooter like movement control"""
from gettext import gettext as _
from OpenGLContext.move import smooth
from OpenGLContext import arrays
from OpenGLContext.events import timer 
from OpenGLContext.scenegraph import interpolators
import math

class FPS( smooth.Smooth ):
    """FPS-style movement
    
        Mouse-captured orientations.
        Jump
    """