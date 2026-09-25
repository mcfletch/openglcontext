"""The forced exit the capture and regression paths end a subprocess with.

:func:`flush_and_exit` lives in :mod:`OpenGLContext.processexit`, which imports
nothing of the engine so that a shipped game can end through it; it is named
here too for the test machinery that ends its subprocesses the same way.
"""

from OpenGLContext.processexit import flush_and_exit

__all__ = ['flush_and_exit']
