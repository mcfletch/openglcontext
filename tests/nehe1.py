#! /usr/bin/env python
'''=Context Setup (NeHe 1)=

[nehe1.py-screen-0001.png Screenshot]

This tutorial is based loosely on the [http://nehe.gamedev.net/data/lessons/lesson.asp?lesson=01 NeHe1 tutorial] by Jeff Molofee, though the code is entirely unique to OpenGLContext.  It demonstrates the creation of a basic rendering Context. Note: OpenGLContext takes care of most of the setup seen in the NeHe code (though doing so also means that there's less direct control of the setup process), leaving a very simple core script.

The first thing we do is get a Context class.  OpenGLContext provides a "testingcontext" module which allows you to use whatever context-type the user has specified as "prefered".  The testingcontext module provides a function "getInteractive" which takes an optional type of context-name to retrieve, and returns an appropriate Context sub-class.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
'''We make the standard OpenGL commands available to our code using an import * statement.'''
from OpenGL.GL import *
'''Now we sub-class the BaseContext class we got in stage one with our own "TestContext" class.  In this very simple example this stage is not actually necessary, as we have no customisations of the class that we want to do, but it is the "normal" approach to using OpenGLContext Contexts.'''

class TestContext( BaseContext ):
    """A subclass of the (dynamically determined) BaseContext,
    by overriding various methods, we could customize the
    functionality of this context, but the tutorial doesn't
    ask us to do this."""
'''And finally, we run our Context's utility "ContextMainLoop", which starts whatever GUI event loop is appropriate for the type of context we have.'''

if __name__ == "__main__":
    TestContext.ContextMainLoop()