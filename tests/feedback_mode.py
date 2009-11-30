from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *

class TestContext( BaseContext ):
    """Feedback-mode testing context"""
    def Render( self, mode = 0):
        """Render the geometry for the scene."""
        if mode.visible:
            # test overflow...
            glFeedbackBuffer( 3, GL_2D )
            glRenderMode( GL_FEEDBACK )
            for x in range( 5 ):
                glPassThrough( float(x) )
            try:
                result = glRenderMode( GL_RENDER )
            except GLerror, err:
                print 'Got expected overflow error', err
            else:
                print "Didn't get overflow error, got %r"%( result, )
            # test 0-length
            glFeedbackBuffer( 3, GL_2D )
            glRenderMode( GL_FEEDBACK )
            try:
                result = glRenderMode( GL_RENDER )
            except GLerror, err:
                print "Failed retriving 0-length result-set", err
            else:
                if len(result) > 0:
                    print "Got unexpectedly long result-set", list(result)
                else:
                    print "Got expected 0-length result-set", list(result)
            # test values passed through
            glFeedbackBuffer( 6, GL_2D )
            glRenderMode( GL_FEEDBACK )
            for x in range( 3 ):
                glPassThrough( float(x) )
            try:
                result = glRenderMode( GL_RENDER )
            except GLerror, err:
                print "Failed retriving 0-length result-set", err
            else:
                result = list(result)
                if result != [
                    (GL_PASS_THROUGH_TOKEN,0.0),
                    (GL_PASS_THROUGH_TOKEN,1.0),
                    (GL_PASS_THROUGH_TOKEN,2.0),
                ]:
                    print "Got wrong results for pass-throughs", result
                else:
                    print "Got expected results for pass-through", result
##			import pdb
##			pdb.set_trace()
                

if __name__ == "__main__":
    TestContext.ContextMainLoop()
