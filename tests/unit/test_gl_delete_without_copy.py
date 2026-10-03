"""GL names are deleted without handing PyOpenGL a list.

``OpenGL.ERROR_ON_COPY`` makes a list argument an error, since turning it into
an array copies it, and a program that sets it must be able to run the engine's
teardown paths.  ``glDeleteX(1, numpy.array([name], dtype=numpy.uint32))``
passes the name as a one-value ``GLuint`` array, which PyOpenGL uses as it is.
"""
import re
from pathlib import Path

import OpenGLContext

LIST_DELETE = re.compile(
    r"glDelete(?:Framebuffers|Textures|Renderbuffers|Buffers|VertexArrays|Queries)"
    r"\(\s*(?:\w+\s*,\s*)?\["
)


def test_no_single_name_delete_passes_a_list():
    root = Path(OpenGLContext.__file__).parent
    found = [
        f'{path.relative_to(root)}:{number}'
        for path in root.rglob('*.py')
        for number, line in enumerate(path.read_text(encoding='utf-8').splitlines(), 1)
        if LIST_DELETE.search(line)
    ]
    assert not found
