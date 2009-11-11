#! /usr/bin/env python
"""Collector package that installs OpenGLContext with all options"""
from setuptools import setup
if __name__ == "__main__":
    setup (
        name = "OpenGLContext-full",
        version = '2.1.0a7',
        description = "Installs all of OpenGLContext with optional dependencies",
        author = "Mike C. Fletcher",
        author_email = "mcfletch@users.sourceforge.net",
        url = "http://pyopengl.sourceforge.net/context/",
        license = "BSD",
        
        install_requires = [
            'setuptools',
            'PyOpenGL',
            'PyOpenGL-accelerate',
            'OpenGLContext',
            'PyVRML97',
            'PyVRML97-accelerate',
            'SimpleParse',
            #'numpy',
            # likely need to provide system-built for most users
            # as building from source misses e.g. JPEG support on 
            # Linux...
            #'Imaging', 
            'PyDispatcher',
            'fonttools',
            'TTFQuery',
        ],
        dependency_links = [
            # fonttools doesn't work off SF...
            'http://downloads.sourceforge.net/project/fonttools/Source%20code/2.3/fonttools-2.3.tar.gz?use_mirror=cdnetworks-us-2',
            # Imaging is registered as PIL, but named Imaging...
            'http://effbot.org/downloads/',
        ],
        
    )
