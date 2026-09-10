"""PyInstaller hooks for OpenGLContext

PyInstaller finds these through the ``pyinstaller40`` entry point declared in
``pyproject.toml``: it calls :func:`get_hook_dirs` and reads every
``hook-*.py`` in the directory returned. An application freezing itself needs
to do nothing to switch them on, and nothing here is imported when the engine
is merely used.

What an application does choose is in :mod:`OpenGLContext.packaging`.
"""

import os
from typing import List


def get_hook_dirs() -> List[str]:
    """Directories PyInstaller should read hooks from"""
    return [os.path.dirname(__file__)]
