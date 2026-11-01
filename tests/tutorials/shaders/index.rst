(Modern) Shader Based Rendering 
===============================

OpenGL 1.x fixed function features, such as display lists, individual
per-vertex calls (glVertex, glColor, etc), the glTranslate, glRotate,
and glScale calls are all deprecated and shouldn't be used in new code.

This tutorial shows you how to do modern OpenGL 3.3+ graphics directly,
in the same way that you would do that work in C or C++. It does not
use many features of OpenGLContext as a result.

It introduces you to the GL Shading Language (GLSL) and how to write
basic shaders. The shaders you write will not be anywhere near as 
complex as the shaders in the OpenGLContext engine itself, but the
core principles will carry forward, and OpenGLContext an extension
of what you will learn here into a working engine.

We assume you know:

* High-school level algebra and geometry (coordinate systems, some 
  basic trigonometry if you want to understand the math involved)
* How to use the command line (shell) on your machine
* Python programming, including how to use `uv <https://docs.astral.sh/uv/>`__ for package management

Software Setup
--------------

You likely want to use `uv` to manage your environment,
if you don't have uv already, you can download it directly, or you
can use pip to install it with `pip install uv`.

To set up the package on a Linux Machine using uv::

    mkdir tutorial
    cd tutorial
    uv init
    uv add 'openglcontext[gltf,glfw]>3.0.0a2'
    uv sync
    source .venv/bin/activate

Hardware
---------

This tutorial needs an OpenGL 3.3 core profile, which is what
OpenGLContext asks for by default and what every desktop driver 
since around 2014 or so provides.  The shaders are written in GLSL
330 which should always be available on a 3.3 core profile driver.

Even a MacOS system *should* have an OpenGL 3.3+ core profile.
Windows systems may only have a *software* (slow) renderer available 
unless your machine has an OpenGL driver installed, but there is 
nothing in these tutorials that should tax even a software renderer.
Linux desktop systems generally install a 3D accelerated driver, but 
it may not be the fastest available driver when using NVIDIA hardware.