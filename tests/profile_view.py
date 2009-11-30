#! /usr/bin/env python
'''Demonstration of profiling a vrml_view context.  Requires PyGame
'''
from OpenGLContext.testingcontext import getVRML
BaseContext = getVRML()
from OpenGLContext import vrmlcontext
import sys
USE_HOTSHOT = 1

class TestContext( 
    BaseContext 
):
    """VRML97-loading Context testing class for use with profiling"""
    def OnInit( self ):
        """Load the image on initial load of the application"""
        filename = sys.argv[1]
        self.load( filename )
        vrmlcontext.VRMLContext.OnInit( self )
        BaseContext.OnInit( self )

if __name__ == "__main__":
    usage = """vrml_view.py myscene.wrl [profilefile]

    Profiles the display/running of a VRML scene
    """
    import sys
    if not sys.argv[1:2]:
        print usage
        sys.exit(1)
    if USE_HOTSHOT:
        import hotshot, tempfile, hotshot.stats
        if sys.argv[2:3]:
            profiler = hotshot.Profile( sys.argv[2], lineevents=0)
            profiler.run( "TestContext.ContextMainLoop()")
            profiler.close()
            print """Profile data written to: %s"""%( sys.argv[2], )
        else:
            temp = tempfile.mktemp( "OpenGLContext.profiler" )
            profiler = hotshot.Profile( temp, lineevents=1 )
            profiler.run( "TestContext.ContextMainLoop()")
            profiler.close()
            print """Starting display of profiling results (may take a while)..."""
            stats = hotshot.stats.load( temp )
            stats.strip_dirs()
            stats.sort_stats('time', 'calls')
            stats.print_stats(20)
            try:
                os.remove(temp)
            except:
                pass
    else:
        print 'Using regular profiler'
        import profile, os
        if sys.argv[2:3]:
            filename = os.path.abspath( sys.argv[2] )
            print """Filename""", filename
            profile.run( "TestContext.ContextMainLoop()", filename)
            print """Profile data written to: %s"""%( filename, )
        else:
            profile.run( "TestContext.ContextMainLoop()")