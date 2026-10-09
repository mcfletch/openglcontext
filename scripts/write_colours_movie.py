#! /usr/bin/env python
"""Write ``tests/resources/colours.mp4``, the movie the MovieTexture tests play.

Eight solid colours, a quarter of a second each, 160 by 128 pixels: red,
green, blue, yellow, cyan, magenta, white and black. Encoded with
pyopengl-video's hardware H.264 encoder from a hidden GLFW window, so it needs
an encoder and, for VA-API, an EGL context (GLFW on Wayland makes one).

    python scripts/write_colours_movie.py [PATH]
"""
from __future__ import annotations

import os
import sys

#: The frames, in order.
COLOURS = ((1, 0, 0), (0, 1, 0), (0, 0, 1), (1, 1, 0), (0, 1, 1), (1, 0, 1), (1, 1, 1),
           (0, 0, 0))
SIZE = (160, 128)
FPS = 4
TARGET = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      'tests', 'resources', 'colours.mp4')


def main(path: str = TARGET) -> int:
    """Encode the frames to `path`"""
    import glfw
    from OpenGL import GL
    from pyopengl_video import open_encoder
    from pyopengl_video.mp4 import MP4Writer

    if not glfw.init():
        print('GLFW could not start')
        return 1
    glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
    glfw.window_hint(glfw.CONTEXT_CREATION_API, glfw.EGL_CONTEXT_API)
    glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 3)
    glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 3)
    glfw.window_hint(glfw.OPENGL_PROFILE, glfw.OPENGL_CORE_PROFILE)
    window = glfw.create_window(*SIZE, 'colours', None, None)
    glfw.make_context_current(window)
    try:
        # Constant quality at a low quantiser, a key frame each second.
        with open_encoder(*SIZE, fps=FPS, gop=FPS, rate_control='cqp', qp=10) as encoder:
            inputs = [encoder.new_input() for _ in range(encoder.input_slots)]
            with MP4Writer(path, encoder) as movie:
                for index, colour in enumerate(COLOURS):
                    target = inputs[index % len(inputs)]
                    with target.for_drawing():
                        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, target.framebuffer)
                        GL.glViewport(0, 0, *SIZE)
                        GL.glClearColor(*colour, 1.0)
                        GL.glClear(GL.GL_COLOR_BUFFER_BIT)
                        GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
                    movie.write(encoder.encode(target, timestamp=index * encoder.timescale // FPS))
                movie.write(encoder.flush())
    finally:
        glfw.destroy_window(window)
        glfw.terminate()
    print('wrote %s' % (path,))
    return 0


if __name__ == '__main__':
    sys.exit(main(*sys.argv[1:]))
