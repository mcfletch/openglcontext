#! /usr/bin/env python
'''=X3D: a film on three screens, looped, reversed and started by a key=

[x3d_movie.py-screen-0001.png Screenshot]

``oglc-x3d-movie`` opens ``x3d_movie.x3d``, an X3D 4 document with three
``MovieTexture`` screens in brushed steel frames on a brick wall:

* the left-hand screen plays the film looped, from when the scene loads;
* the centre screen plays it looped at ``speed`` -1, so its dial turns
  backwards and its bar empties, sampled through a ``TextureProperties``;
* the right-hand screen waits on the film's first frame until ``s`` starts
  it, and darkens its edges through a ``MultiTexture`` that modulates the
  movie by a second, grey texture.

The film is drawn by the engine and encoded with pyopengl-video's hardware
H.264 encoder, then decoded on the GPU into the screens' textures. On a
machine with no encoder or no decoder for this context the script says
which, and exits with the status that marks a capture skipped.
'''
import os
import sys
import tempfile

os.environ.setdefault('OPENGLCONTEXT_RENDERER', 'pbr')
'''A capture is drawn at a second and a half into the scene's clock, so the
looping screen is part way through the film and the reversed one part way
back.'''
os.environ.setdefault('OPENGLCONTEXT_CAPTURE_START', '1.5')

from OpenGLContext import testingcontext
from OpenGLContext.context import Context as BaseContext
from OpenGLContext.bin.x3d_movie import FilmUnavailable, MovieScene, make_film
from OpenGLContext.events import systemtime
from OpenGLContext.loaders import background


def unavailable():
    '''What stops this context playing a film made here; '' where nothing does.

    The decoder has to read into this window's context, which on Linux means
    an EGL context; the encoder runs in a process of its own.'''
    try:
        from pyopengl_video import decoder
    except ImportError:
        return 'pyopengl-video is not installed (OpenGLContext[video])'
    if not list(decoder.available_backends()):
        return 'no video decoder for this context: %s' % (
            '; '.join(decoder.explanations()) or 'none here')
    return ''


class TestContext(BaseContext):

    def OnInit(self):
        '''The film is made first, in a process of its own; then the room is
        copied beside it and read with ``Loader.load``.'''
        reason = unavailable()
        directory = tempfile.mkdtemp(prefix='x3d-movie-')
        if not reason:
            try:
                film = make_film(os.path.join(directory, 'film.mp4'))
            except FilmUnavailable as err:
                reason = 'no film: %s' % (err,)
        if reason:
            print(reason)
            sys.exit(testingcontext.REQUIRED_EXTENSION_MISSING)
        self.movies = MovieScene(directory, film)
        background.wait_for_idle(20.0)
        self.sg = self.movies.scene
        '''``s`` starts the right-hand film and ``p`` pauses the left-hand
        one, at the engine's time.'''
        for key in MovieScene.KEYS:
            self.addEventHandler('keypress', name=key, function=self.OnKey)
        print(MovieScene.help())

    def OnKey(self, event):
        said = self.movies.press(event.name, systemtime.systemTime())
        if said:
            print(said)
            self.triggerRedraw(True)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
