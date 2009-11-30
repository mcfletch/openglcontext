#!/usr/bin/env python
"""Installs OpenGLContext using setuptools

Run:
    python setup.py install
to install the package from the source archive.
"""
from distutils.core import setup
import sys, os
sys.path.insert(0, '.' )

def find_version( ):
    for line in open( os.path.join(
        'OpenGLContext','__init__.py',
    )):
        if line.strip().startswith( '__version__' ):
            return eval(line.strip().split('=')[1].strip())
    raise RuntimeError( """No __version__ = 'string' in __init__.py""" )

version = find_version()

def is_package( path ):
    return os.path.isfile( os.path.join( path, '__init__.py' ))
def find_packages( root ):
    """Find all packages under this directory"""
    for path, directories, files in os.walk( root ):
        if is_package( path ):
            yield path.replace( '/','.' )

if __name__ == "__main__":
    extraArguments = {
        'classifiers': [
            """License :: OSI Approved :: BSD License""",
            """Programming Language :: Python""",
            """Programming Language :: C""",
            """Topic :: Software Development :: Libraries :: Python Modules""",
            """Topic :: Multimedia :: Graphics :: 3D Rendering""",
            """Intended Audience :: Developers""",
            """Environment :: X11 Applications""",
            """Environment :: Win32 (MS Windows)""",
        ],
        'download_url': "https://sourceforge.net/projects/pyopengl/files/OpenGLContext",
        'keywords': 'PyOpenGL,OpenGL,Context,OpenGLContext,render,3D,TrueType,text,VRML,VRML97,scenegraph',
        'long_description' : """Demonstration and Testing Contexts for PyOpenGL

OpenGLContext includes rendering contexts (including navigation)
for wxPython, PyGame and GLUT, as well as a partial context for
Tkinter.  It also includes support for rendering TrueType fonts,
and a significant subset of VRML97.  It provides fairly extensive
VRML97 scenegraph model.  It also includes the bulk of the tests
used to maintain and extend PyOpenGL.
""",
        'platforms': ['Win32','Linux','OS-X','Posix'],
    }
    ### Now the actual set up call
    setup (
        name = "OpenGLContext",
        version = version,
        description = "Demonstration and testing contexts for PyOpenGL/OpenGL-ctypes",
        author = "Mike C. Fletcher",
        author_email = "mcfletch@users.sourceforge.net",
        url = "http://pyopengl.sourceforge.net/context/",
        license = "BSD-style, see license.txt for details",

        packages = list(find_packages('OpenGLContext')),
        # need to add executable scripts too...
        options = {
            'sdist': {
                'formats':['gztar','zip'],
            }
        },
        # non python files of examples      
        **extraArguments
    )