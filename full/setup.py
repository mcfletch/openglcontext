#! /usr/bin/env python
"""Collector package that installs OpenGLContext with all options"""
from setuptools import setup

import sys
if sys.hexversion < 0x2050000:
    simpleparse = 'SimpleParse==2.0.1a3'
    simpleparse_link = 'http://sourceforge.net/projects/simpleparse/files/simpleparse/2.0.1a3'
else:
    simpleparse = 'SimpleParse'
    simpleparse_link = ''

if __name__ == "__main__":
    setup (
        name = "OpenGLContext-full",
        version = '2.1.0a9',
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
            simpleparse,
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
            # 'http://downloads.sourceforge.net/project/fonttools/Source%20code/2.3/fonttools-2.3.tar.gz?use_mirror=cdnetworks-us-2',
            'http://cdnetworks-us-1.dl.sourceforge.net/project/fonttools/2.3/fonttools-2.3.tar.gz',
            # Imaging is registered as PIL, but named Imaging...
            'http://effbot.org/downloads/',
            simpleparse_link,
        ],

    )
