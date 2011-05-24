#! /usr/bin/env python
'''Test OpenGL ARB Sync extension
'''
import OpenGL 
OpenGL.USE_ACCELERATE = False
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GL.ARB.sync import *

SECOND_TO_NANO = 10**9 # 1 billionth of a second...

def second_to_nano( x ):
    return long( x * SECOND_TO_NANO )

EXPECTED = {
    GL_SIGNALED:GL_SIGNALED,
    GL_UNSIGNALED:GL_UNSIGNALED,
}

class TestContext( BaseContext ):
    def OnInit( self ):
        if not glFenceSync:
            print 'Do not have the ARB sync extension available'
            raise SystemExit( 1 )
    def Render( self, mode=None ):
        fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0)
        TIMEOUT = second_to_nano(.25)
        status = glClientWaitSync(fence, 0, TIMEOUT )
        if status == GL_ALREADY_SIGNALED:
            print 'Already signalled'
        elif status == GL_TIMEOUT_EXPIRED:
            print 'Timed out'
        elif status == GL_CONDITION_SATISFIED:
            print 'Success'
        elif status == GL_WAIT_FAILED:
            print 'Wait failure, should have raised an error before we got here'
        else:
            print 'Unknown return status'
        result = GLint()
        glGetSynciv( fence, GL_SYNC_STATUS, 1, GLsizei(), result )
        print 'Get result', EXPECTED.get(result.value,result.value)
        
        # wrapped style...
        result = glGetSync( fence, GL_SYNC_STATUS )[0]
        print 'Wrapped get', EXPECTED.get(result,result)
        
        glDeleteSync( fence )
        
        range,precision = glGetShaderPrecisionFormat( GL_VERTEX_SHADER, GL_HIGH_FLOAT )
        print 'Precision formats', range, precision
        

if __name__ == "__main__":
    TestContext.ContextMainLoop()
