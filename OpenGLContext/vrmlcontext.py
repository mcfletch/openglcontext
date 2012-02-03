#! /usr/bin/env python
"""VRML97-aware Context Mix-in

Purpose of this module is to provide the common requirements
for a VRML97 viewer, such as frame-rate reporting, extraction
of viewpoint, and similar useful things.
"""
from OpenGL.GL import *
from OpenGL.GLU import *
import os, sys, time, traceback
from OpenGLContext import framecounter
from OpenGLContext.loaders.loader import Loader
import logging
log = logging.getLogger( __name__ )

class VRMLContext(object):
    """VRML97-loading Context testing class

    Major problem here is that we're using testingcontext,
    when what we want to do is make this a true mix-in that
    defers to it's superclass in the context's MRO,
    unfortunately, wxPython 2.4 won't allow us to use super,
    so we're stuck with this at the moment.
    """
    initialPosition = (0,0,10)
    USE_FRUSTUM_CULLING = 1
    USE_OCCLUSION_CULLING = 0
    sg = None
    def setupFontProviders( self ):
        """Load font providers for the context

        See the OpenGLContext.scenegraph.text package for the
        available font providers.
        """
        from OpenGLContext.scenegraph.text import fontprovider
        try:
            from OpenGLContext.scenegraph.text import toolsfont
            registry = self.getTTFFiles()
        except ImportError, err:
            log.warn( """Unable to import TTFQuery/FontTools-based TTF-file registry, no TTF font support!""" )
        else:
            fontprovider.setTTFRegistry(
                registry,
            )
        try:
            from OpenGLContext.scenegraph.text import pygamefont
        except (ImportError,NotImplementedError):
            log.warn( """Unable to import PyGame TTF-font renderer, no PyGame anti-aliased font support!""" )
        try:
            from OpenGLContext.scenegraph.text import glutfont
        except ImportError:
            log.error( """Unable to import GLUT-based font renderer, no GLUT bitmap font support (this is unexpected)!""" )
        
    def OnInit( self ):
        """Initialise the VRMLContext keyboard shortcuts"""

    def load( self, filename ):
        """Load given url, replacing current scenegraph"""
        self.sg = Loader.load( filename )
        
