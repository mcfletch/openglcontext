"""VRML97 context for GLUT
"""
from OpenGLContext import glutinteractivecontext
from OpenGLContext import vrmlcontext
import os, glob
from OpenGL.GLUT import *

class VRMLContext(
    vrmlcontext.VRMLContext,
    glutinteractivecontext.GLUTInteractiveContext
):
    """GLUT-specific VRML97-aware Testing Context"""
    worldPaths = []
    def createMenus( self ):
        """Create pop-up menus for the VRML97 context"""
        # get the list of all VRML97 files in our sub-directory
        from OpenGLContext import tests
        from OpenGLContext.tests.resources import test_vrml_set_txt
        base = os.path.join( os.path.dirname( tests.__file__ ), 'wrls', '*.wrl' )
        paths = glob.glob( base )
        fileMenu = glutCreateMenu(self.OnMenuLoad)
        for path in paths:
            self.worldPaths.append( path )
            index = len(self.worldPaths)-1
            glutAddMenuEntry(os.path.join( 'wrls',os.path.basename(path)), index)
        urlMenu = glutCreateMenu(self.OnMenuLoad)
        for path in [
            line.strip()
            for line in test_vrml_set_txt.data.split( '\n')
            if (line.strip() and not line.strip().startswith( '#' ))
        ]:
            self.worldPaths.append( path )
            index = len(self.worldPaths)-1
            glutAddMenuEntry(path, index)
        loadMenu = glutCreateMenu(self.OnMenuLoad)
        glutAddSubMenu( "Load File", fileMenu )
        glutAddSubMenu( "Load URL", urlMenu )
        glutAttachMenu(GLUT_MIDDLE_BUTTON)
        return loadMenu
    def OnMenuLoad( self, item ):
        """React to a menu-load event"""
        self.load( self.worldPaths[ item ] )
        self.platform.setPosition( self.initialPosition )
        self.platform.setOrientation( self.initialOrientation )
        self.triggerRedraw( force=1)


BaseContext = VRMLContext