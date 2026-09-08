"""A stand-in for a program that settles the renderer as it is imported.

Several of this project's own entry points do -- ``oglc-gltf-view`` and its
siblings -- because a program that is about to draw has to choose before
``OpenGL`` loads. This is what
:func:`OpenGLContext.testing.gl_env.import_unconfigured` is held to, without
importing one of them and taking whatever it happens to want this week.

Not named ``test_*``, so pytest does not collect it; it is imported by name.
"""

import os

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')

#: What it settled on, so a test can tell the module was actually imported.
WHAT_IT_ASKED_FOR = os.environ['OPENGLCONTEXT_RENDERER']
