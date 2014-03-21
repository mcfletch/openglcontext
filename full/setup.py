#! /usr/bin/env python
"""Collector package that installs OpenGLContext with all options"""
from setuptools import setup
import sys

if __name__ == "__main__":
    setup (
        name = "OpenGLContext-full",
        version = '3.1.0b1',
        description = "Installs all of OpenGLContext with optional dependencies",
        author = "Mike C. Fletcher",
        author_email = "mcfletch@vrplumber.com",
        url = "http://pyopengl.sourceforge.net/context/",
        license = "BSD",

        install_requires = [
            'PyOpenGL >= 3.1.0b1',
            'PyOpenGL-accelerate >= 3.1.0b1',
            'OpenGLContext >= 2.3.0b1',
            'PyVRML97 >= 2.3.0b1',
            'PyVRML97-accelerate >= 2.3.0b1',
            'SimpleParse',
            'numpy',
            'PyDispatcher',
            'FontTools',
            'TTFQuery',
            'pillow',
        ],
    )
