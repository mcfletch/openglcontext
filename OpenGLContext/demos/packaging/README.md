# Shipping an embedded viewer

The two ways an application built on the engine reaches somebody who has no
Python, worked through on the Tk demo beside this.  The Qt demo has the same
pair in `OpenGLContext_qt/demos/packaging/`; between them they cover both
shapes, and an application of your own is the same files with a different name
in them.

Neither is specific to a *demo*.  What is here is what any application on the
engine writes, and it is short because the engine answers the parts it is the
one that knows -- which modules are reached by name, which toolkits are not
being used, which libraries the machine is asked for.  See
[docs/packaging.html](../../../docs/packaging.html).

## A frozen bundle

    pyinstaller OpenGLContext/demos/packaging/viewer-demos.spec

`dist/viewer-demos/` is then a directory holding a Python runtime, the engine
and the demo, entered through `oglc-tk-viewer`.  Zip it and it runs on a machine
with a graphics driver and nothing else -- about 130 MB, most of it numpy,
Pillow and the interpreter.

* [`viewer-demos.spec`](viewer-demos.spec) -- what PyInstaller is told.  Almost
  all of it is the same for any application; the line that is not is
  `unused_backend_modules(keep=['tk'])`, which leaves out the toolkits this one
  does not use.  Qt alone is a quarter of a gigabyte.
* [`entry.py`](entry.py) -- the commands the bundle offers, one executable each
  from a single copy of the libraries.

PyInstaller builds for the machine it runs on, so a Windows bundle is built on
Windows.

## A Debian package

    OpenGLContext/demos/packaging/build-deb.sh

`dist/openglcontext-viewer-demo_1.0.0-1_amd64.deb` installs under
`/opt/openglcontext-viewer-demo`, links `oglc-tk-viewer` into `/usr/bin` and
adds a desktop menu entry.  It carries its own Python: no system interpreter, no
virtual environment for the user to make, no pip at install time.

* [`build-deb.sh`](build-deb.sh) -- fetches a relocatable CPython and calls
  `oglc-deb`.  The options that are not obvious are commented in it, the
  important one being `--backend tk`.
* [`deb-project/`](deb-project) -- the demo as a *distribution*.  A package needs
  a console script to put in `/usr/bin` and to name in a menu entry, and
  `OpenGLContext.demos` deliberately declares none, so shipping one means making
  it an application.  For this demo that is a `pyproject.toml` and nothing else;
  for an application of your own it is the one you already have.

Until the engine stack is on PyPI, pass the requirements file that pins it:

    OpenGLContext/demos/packaging/build-deb.sh -r requirements-stack.txt

`oglc-deb` builds for the architecture of the interpreter it is given, and there
is no cross-architecture build: the wheels installed into the environment are
the build machine's.

## What neither of them carries

No scene.  The demos open whatever they are given on the command line, and a
model an application fetches or generates at run time is not something a package
can hold.
