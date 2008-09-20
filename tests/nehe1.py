#! /usr/bin/env python
"""Basic Context setup and display

Although named Nehe1, this file is entirely
created from scratch.  It gives you the same
results as the Nehe first tutorial, but is...
well... ridiculously simple, since all of the
functionality is handled by the OpenGLContext
modules.
"""
## Following two lines get a testing context class
## and a function which can initialize that class
from OpenGLContext import testingcontext
BaseContext, MainFunction = testingcontext.getInteractive()

## Makes the OpenGL.GL functions available within the
## module's environment.  The * form of import is
## used because of the huge number of OpenGL functions
## that tend to be used in a normal OpenGL program.
## 
## We don't actually use any GL functions, but we might
## as well include this, since there isn't much else
## to discuss.
from OpenGL.GL import *

class TestContext( BaseContext ):
	"""A subclass of the (dynamically determined) BaseContext,
	by overriding various methods, we could customize the
	functionality of this context, but the tutorial doesn't
	ask us to do this."""

if __name__ == "__main__":
	## We only want to run the main function if we
	## are actually being executed as a script
	MainFunction ( TestContext)

