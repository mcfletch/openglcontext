"""The GLFW shared library, which its bindings open by path

``glfw`` is the backend the engine recommends for the core profile, and the
one an application on this stack normally freezes. Its bindings load the
library with ``ctypes`` from a path they work out at run time -- including,
already, the paths a frozen application has -- so all that is missing is the
file itself, which no import statement mentions.

The Linux wheels carry a build for X11 and one for Wayland and choose between
them from the session type, so both travel: which one a machine wants is not
known when the bundle is built. PyInstaller ships no hook for ``glfw``, so
this one lives with the engine that asks for it.
"""

from PyInstaller.utils.hooks import collect_dynamic_libs

binaries = collect_dynamic_libs('glfw')
