'''=Requirements/Setup=

This tutorial introduces modern, low-level 3D rendering 
techniques.  It tries to avoid the use of "legacy" OpenGL 
entry points as much as possible.  Though legacy OpenGL 
is likely to be supported on most desktop/laptop hardware 
for the foreseeable future, their use is technically 
discouraged.

We assume you know:

    * General programming (with Python)
    * Some highschool level math

== Package Installation ==

This tutorial requires at least the following packages:

    * [http://pyopengl.sourceforge.net/context OpenGLContext] -- provides the overall rendering code ([http://pyopengl.sourceforge.net/documentation/installation.html Installation Notes]).
    * [http://pyopengl.sourceforge.net PyOpenGL] -- the actual 
        rendering interface we're learning to use in this tutorial.
    * [http://numpy.scipy.org/ Numpy] -- provides the multi-dimensional 
        array structures we'll use for passing data into PyOpenGL 
    * [http://sourceforge.net/projects/pyvrml97/ PyVRML97] -- provides 
        a VRML97 rendering and scenegraph mechanism which is core to 
        OpenGLContext
    * [http://pydispatcher.sourceforge.net/ PyDispatcher] -- provides 
        routing/observation support for PyVRML97

For platforms other than Win32 I recommend using 
[http://pypi.python.org/pypi/virtualenv virtualenv] environment in order 
to run this tutorial, as many of the packages above are not available 
in distribution packaging systems yet.  Numpy is normally available on 
Linux platforms with a recent build, so you may wish to use the 
platform build.

To set up the packages on a Linux Machine using virtualenv:'''
"""virtualenv tutorial 
cd tutorial
source bin/activate 
easy_install  OpenGLContext-full"""
'''You'll need to have GLUT, GLE and the like installed via your 
system's package manager.  See the OpenGLContext installation notes 
for details.

== System Requirements ==

This tutorial requires a very modern OpenGL implementation.  Your 
card/driver should likely support OpenGL 2.x natively, though 
OpenGL 1.5+ extensions may work.

It is known *not* to work on the following theoretically capable 
configurations:

    * Mac Radeon 9600, OS-X 10.4/10.5 (does not support vertex 
        attribute arrays)
    * nVidia GeForce 7600 GS rev a1 (does not properly 
        compile the 11th tutorial (link error)).

Note that there are alternative code-paths that can be used, but 
that the tutorial does not currently explore those paths in the 
interest of making the introductory tutorial easier to follow.
'''