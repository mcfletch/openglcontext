#! /usr/bin/env python
"""Collector package that installs OpenGLContext with all options"""
from setuptools import setup
import sys

if __name__ == "__main__":
    setup (
        name = "OpenGLContext-full",
        version = '3.1.1',
        description = "Installs all of OpenGLContext with optional dependencies",
        author = "Mike C. Fletcher",
        author_email = "mcfletch@vrplumber.com",
        url = "http://pyopengl.sourceforge.net/context/",
        license = "BSD",

        install_requires = [
            'PyOpenGL >= 3.1.1',
            'PyOpenGL-accelerate >= 3.1.1',
            'OpenGLContext >= 2.3.0',
            'PyVRML97 >= 2.3.0',
            'PyVRML97-accelerate >= 2.3.0',
            'SimpleParse>=2.2.0',
            'numpy',
            'PyDispatcher',
            'FontTools',
            'TTFQuery',
            'pillow',
        ],
    )
