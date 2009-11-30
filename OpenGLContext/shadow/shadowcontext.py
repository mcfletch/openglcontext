"""Context mix-in providing support for shadow rendering algorithm
"""
from OpenGL.GL import *
from math import pi
from OpenGLContext.move import viewplatform
from OpenGLContext.shadow import pinfperspective, passes
from OpenGLContext.arrays import negative

RADTODEG = 180/pi
### support classes...
class InfViewPlatform( viewplatform.ViewPlatform ):
    """Platform sub-class which creates infinite perspective matrices"""
    def render (self, mode = None):
        """Create perspective matrix for current position and orientation

        Uses pinfperspective to create the infinite perspective
        matrix required by the shadow-rendering algorithm.
        """
        # setup camera
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glLoadMatrixd(pinfperspective.pinfPerspective( * self.frustum))
        glMatrixMode(GL_MODELVIEW)
        x,y,z,r = self.quaternion.XYZR()
        glRotate( r*RADTODEG, x,y,z )
        apply( glTranslate, ( negative (self.position))[:3])

class ShadowContext:
    """Mix-in for contexts wanting stencil-shadow support

    The ShadowContext has two primary customizations,
    the first is the use of:
        OpenGLContext.shadow.passes.defaultRenderPasses
    as the renderPasses member.  This replaces the standard
    rendering-pass set with the shadow-aware set.

    The second customization is the use of an "infinite
    view platform" which is a requirement of the particular
    shadow-casting algorithm we are using.

    Note: this is an old-style class! as are all contexts
    at the moment.  This cannot change until wxPython (at least)
    converts to using new-style classes for its Windows,
    or I reworked the base context to not use inheritance
    for creating the wxPython context.
    """
    renderPasses = passes.defaultRenderPasses
    def getViewPlatform( self ):
        """Get the view platform to use for this context

        Returns an InfViewPlatform, which provides the required
        pinfPerspective-based model-view matrix.
        """
        width,height = self.getViewPort()
        if width==0 or height==0:
            aspect = 1.0
        else:
            aspect = float(width)/float(height)
        return InfViewPlatform(
            position = self.initialPosition,
            orientation = self.initialOrientation,
            aspect=aspect,
        )