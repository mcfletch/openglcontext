'''=Requirements/Setup=

This tutorial introduces modern, low-level 3D rendering
techniques.  Everything in it is drawn the way an OpenGL core
profile draws: data in buffers, described by a vertex array
object, turned into pixels by shaders you write.

We assume you know:

    * General programming (with Python)
    * Some highschool level math

== Package Installation ==

You likely want to use the `uv` tool to manage your environment,
if you don't have uv already, you can download it directly, or you
can use pip to install it with `pip install uv`.

To set up the package on a Linux Machine using uv:'''
"""mkdir tutorial
cd tutorial
uv init
uv add 'openglcontext[gltf,glfw]>3.0.0a2'
uv sync
source .venv/bin/activate
"""
'''
== System Requirements ==

This tutorial needs an OpenGL 3.3 core profile, which is what
OpenGLContext asks for by default and what every desktop driver of
the last decade or so provides.  The shaders are written in GLSL
330.
'''
