"""Build a clean environment for a GL subprocess test.

Test modules set ``OPENGLCONTEXT_*`` variables in ``os.environ`` at import time to
configure their own subprocess drivers. Those writes persist in the parent process,
so a subprocess launched with ``env=dict(os.environ)`` inherits whatever another
module happened to set (profile, renderer, shadows, ...), making its result depend
on collection order. :func:`gl_subprocess_env` avoids that: it starts from only the
system/graphics variables a Python GL child needs and adds exactly the variables the
caller intends, so no leaked application setting can reach the child.
"""

import os

# System, display and GPU-vendor variables a windowed/offscreen GL child needs.
# Application configuration (OPENGLCONTEXT_*, GLTF, ...) is deliberately excluded.
_KEEP_NAMES = frozenset((
    'PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'SHELL', 'TERM', 'TMPDIR',
    'DISPLAY', 'WAYLAND_DISPLAY', 'XAUTHORITY',
    'LD_LIBRARY_PATH', 'LD_PRELOAD',
    'PYTHONPATH', 'PYTHONHASHSEED', 'VIRTUAL_ENV', 'PYOPENGL_PLATFORM',
))
_KEEP_PREFIXES = (
    'XDG_', '__GLX_', '__EGL_', '__NV', '__VK', 'NVIDIA_', 'NV_',
    'LIBGL_', 'MESA_', 'VK_', 'DRI', 'GALLIUM_', 'EGL_', 'GBM_',
)


def gl_subprocess_env(**overrides):
    """Environment for a GL subprocess: infrastructure vars plus ``overrides``.

    Values are stringified. Anything not in the infrastructure allow-list is
    dropped, so an ``OPENGLCONTEXT_*`` setting leaked into the parent by another
    test cannot influence the child -- pass every variable the child depends on
    explicitly as a keyword argument.
    """
    env = {k: v for k, v in os.environ.items()
           if k in _KEEP_NAMES or k.startswith(_KEEP_PREFIXES)}
    env.update({k: str(v) for k, v in overrides.items()})
    return env
