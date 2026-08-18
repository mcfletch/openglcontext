"""Recording what the engine draws.

:class:`~OpenGLContext.video.recorder.VideoRecorder` takes the frame a context
has just drawn and writes it to an H.264 video file, with the frame going
straight from the framebuffer to the GPU's video encoder.

Recording needs the ``video`` extra::

    pip install OpenGLContext[video]

which brings in `pyopengl-video <https://github.com/mcfletch/pyopengl-video>`_,
the encoder bindings. Without it a context runs exactly as before and asking to
record reports what is missing.
"""
