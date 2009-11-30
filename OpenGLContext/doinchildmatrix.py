"""Perform python function within MODELVIEW child matrix

XXX Should add versions for perspective and/or texture
    matrices (use a parameterized base function and
    provide top-level convenience functions to call it).
"""
from OpenGL.GL import *

def doInChildMatrix( function, *args, **named ):
    """Do the function in a "child" matrix

    This method allows you to perform the given function
    within a dependent model-view matrix, with stack-
    overflow protected restoration of the model-view matrix
    after completion (regardless of whether an error
    occurs).
    """
    # This code is not OpenGL 3.1 compatible
    glMatrixMode( GL_MODELVIEW )
    try:
        glPushMatrix()
    except GLerror, error:
        matrix = glGetDouble( GL_MODELVIEW_MATRIX )
        try:
            return function( *args, **named )
        finally:
            glMatrixMode( GL_MODELVIEW )
            glLoadMatrixd( matrix )
    else:
        try:
            return function( *args, **named )
        finally:
            glMatrixMode( GL_MODELVIEW )
            glPopMatrix( )
