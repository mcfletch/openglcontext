#! /usr/bin/env python
"""X3D movies: one film on three screens, looped, reversed and started by a key.

    oglc-x3d-movie [--directory DIR] [--remake] [movie]

    s      start the right-hand screen's film
    p      pause or resume the left-hand screen's film

The document is ``x3d_movie.x3d``, shipped with this module: a room with a
wood floor, a brick wall between plaster walls, and three screens in brushed
steel frames. Each screen is a ``MovieTexture`` playing ``film.mp4``: on the
left looped, in the centre looped at ``speed`` -1 through a
``TextureProperties``, and on the right once, from the ``s`` key, inside a
``MultiTexture`` that darkens its edges.

The film is drawn by the engine from ``x3d_movie_film.x3d`` and encoded with
pyopengl-video's hardware H.264 encoder (:func:`make_film`), in a process of
its own with an offscreen context. Playing it needs a decoder pyopengl-video
drives for the window's context: see docs/x3d.rst, "Movies".

``movie`` names an MP4 file with an H.264 track for the screens to play in
place of that film (:func:`chosen_film`). The screens are 16:9 and the picture
fills them.
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence
from typing import Any, ClassVar, Optional

__all__ = ['DOCUMENT', 'FILM', 'FILM_FPS', 'FILM_SECONDS', 'FILM_SIZE', 'FilmUnavailable',
           'MATERIALS', 'MovieScene', 'NAMED', 'chosen_film', 'main', 'make_film',
           'prepare', 'record_film', 'vignette']

#: The room.
DOCUMENT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_movie.x3d')
#: The scene the film is drawn from.
FILM = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'x3d_movie_film.x3d')
#: The film's size in pixels, its rate in frames a second and its length in seconds.
FILM_SIZE = (384, 216)
FILM_FPS = 30
FILM_SECONDS = 4
#: The surfaces the room names, each written as ``<name>_base.png``,
#: ``<name>_mr.png`` and ``<name>_normal.png``.
MATERIALS = ('wood', 'brick', 'plaster', 'steel')
#: The directory, under the room's, that a movie named on the command line is
#: shown from.
NAMED = 'named'
#: The exit status of a film process that found no encoder.
NO_ENCODER = 3


class FilmUnavailable(RuntimeError):
    """The film could not be made: no encoder here, or the recording failed"""


def _maps(name: str) -> Any:
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 NumPy work only when written
    if name == 'wood':
        return surfaces.wood(256)
    if name == 'brick':
        return surfaces.brick(256)
    if name == 'plaster':
        return surfaces.plaster(256)
    return surfaces.brushed_metal(256, surfaces.STEEL)


def vignette(size: int = 128) -> Any:
    """A grey picture, white in the middle and darker toward its edges, ``(size, size, 3)`` bytes"""
    import numpy as np  # noqa: PLC0415 only when written
    across = np.linspace(-1.0, 1.0, size)
    x, y = np.meshgrid(across, across)
    level = np.clip(1.15 - 0.55 * (x ** 4 + y ** 4), 0.0, 1.0)
    grey = (level * 255.0).astype(np.uint8)
    return np.repeat(grey[:, :, None], 3, axis=2)


def prepare(directory: str, force: bool = False) -> str:
    """The room, copied to `directory` with the images it names

    Images already there are kept unless `force`. The film is
    :func:`make_film`'s. Returns the copy's path.
    """
    from PIL import Image  # noqa: PLC0415 only when written
    from OpenGLContext.atomicfiles import copy_file, staged_file  # noqa: PLC0415 kept with its use
    from OpenGLContext.scenegraph import surfaces  # noqa: PLC0415 only when written
    os.makedirs(directory, exist_ok=True)
    target = os.path.join(directory, os.path.basename(DOCUMENT))
    copy_file(DOCUMENT, target)
    for name in MATERIALS:
        paths = [os.path.join(directory, '%s_%s.png' % (name, part))
                 for part in ('base', 'mr', 'normal')]
        if force or not all(os.path.exists(path) for path in paths):
            for path, pixels in zip(paths, surfaces.images(_maps(name)), strict=True):
                with staged_file(path) as handle:
                    Image.fromarray(pixels, 'RGB').save(handle, 'PNG')
    path = os.path.join(directory, 'vignette.png')
    if force or not os.path.exists(path):
        with staged_file(path) as handle:
            Image.fromarray(vignette(), 'RGB').save(handle, 'PNG')
    return target


def make_film(path: str, force: bool = False, timeout: float = 120.0) -> str:
    """The film at `path`, recorded by :func:`record_film` in a process of its own

    A film already there is kept unless `force`, and the directory is made
    where it is missing. The process opens an offscreen context, which on
    Linux is an EGL context the VA-API encoder can read from, with none of the
    parent's rendering variables. Raises :class:`FilmUnavailable` with the
    reason where no film was made. Returns `path`.
    """
    from OpenGLContext import renderoptions  # noqa: PLC0415 kept with its use
    if os.path.exists(path) and not force:
        return path
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    try:
        # The rendering variables a capture carries (a frame count to exit
        # after, above all) would end the recording early.
        result = subprocess.run(
            [sys.executable, '-m', 'OpenGLContext.bin.x3d_movie', '--film', path],
            capture_output=True, text=True, timeout=timeout,
            env=renderoptions.clean_environment())
    except subprocess.TimeoutExpired as err:
        raise FilmUnavailable('recording the film took over %d seconds' % timeout) from err
    if result.returncode != 0 or not os.path.exists(path):
        lines = (result.stdout + result.stderr).strip().splitlines()
        raise FilmUnavailable(lines[-1] if lines else 'the film process exited %d'
                              % result.returncode)
    return path


def chosen_film(directory: str, movie: Optional[str] = None,
                remake: bool = False) -> tuple[str, str]:
    """The room's directory and the film its screens play

    With no `movie`, the film is :func:`make_film`'s in `directory`, recorded
    again where `remake`. A `movie` is shown from the :data:`NAMED` directory
    under `directory`: the document reads ``film.mp4`` beside itself, and the
    copy made there leaves the film made here in place. Raises
    :class:`FilmUnavailable` where `movie` is not a file or the film could
    not be made.
    """
    if movie is None:
        return directory, make_film(os.path.join(directory, 'film.mp4'), force=remake)
    if not os.path.isfile(movie):
        raise FilmUnavailable('%s is not a file' % (movie,))
    return os.path.join(directory, NAMED), movie


def record_film(path: str) -> int:  # pragma: no cover - runs in the film process, with an encoder
    """Draw the film scene offscreen and record :data:`FILM_SECONDS` of it to `path`

    The world clock starts at 0 and advances a frame at a time, so the film
    is the same every time it is made. Returns the exit status: 0, or
    :data:`NO_ENCODER` with the reason printed where nothing here encodes.
    """
    from OpenGLContext.context import Context  # noqa: PLC0415 a context only for the film
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a context only for the film
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 a context only for the film
    from OpenGLContext.video.clock import FixedStepClock  # noqa: PLC0415 a context only for the film
    from OpenGLContext.video.recorder import (  # noqa: PLC0415 a context only for the film
        RecordingMixin, RecordingUnavailable,
    )

    class FilmContext(RecordingMixin, Context):
        windowSystemName = 'offscreen'

        def OnInit(self) -> None:
            FixedStepClock(FILM_FPS, start=0.0).install()
            self.sg = Loader.load(FILM)
            self.setupRecording(path, fps=FILM_FPS, frames=FILM_FPS * FILM_SECONDS,
                                size=FILM_SIZE)

        def presentFrame(self) -> Any:
            try:
                self.tickRecording()
            except RecordingUnavailable as err:
                print('no encoder: %s' % (err,), flush=True)
                os._exit(NO_ENCODER)  # noqa: TID251 the film process has nothing to flush
            return super().presentFrame()

    FilmContext.ContextMainLoop(definition=ContextDefinition(
        title='film', size=FILM_SIZE, renderer='pbr'))
    return 0


class MovieScene:
    """The room with no window: what the demo and its tests share

    `directory` receives the document and its images; `film` is the movie
    the screens play, copied beside the document as ``film.mp4`` where it is
    somewhere else. ``scene`` is the document read by the engine's loader.
    """

    KEYS: ClassVar[dict[str, str]] = {
        's': "start the right-hand screen's film",
        'p': "pause or resume the left-hand screen's film",
    }

    def __init__(self, directory: str, film: str) -> None:
        from OpenGLContext.atomicfiles import copy_file  # noqa: PLC0415 kept with its use
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
        self.directory = directory
        self.path = prepare(directory)
        beside = os.path.join(directory, 'film.mp4')
        if os.path.abspath(film) != os.path.abspath(beside):
            copy_file(film, beside)
        self.scene = Loader.load(self.path)

    def node(self, name: str) -> Any:
        """The node the document DEFs as `name`"""
        return self.scene.getDEF(name)

    def press(self, key: str, now: float) -> str:
        """Answer a key at the engine's time `now`; what it did, for the console"""
        if key == 's':
            keyed = self.node('Keyed')
            if keyed.running():
                return 'the right-hand film is already playing'
            keyed.startTime = now
            return 'right-hand film started'
        if key == 'p':
            looping = self.node('Looping')
            if looping.paused():
                looping.resume(now)
                return 'left-hand film resumed'
            looping.pause(now)
            return 'left-hand film paused'
        return ''

    @classmethod
    def help(cls) -> str:
        """The keys, one to a line"""
        return '\n'.join('  %s  %s' % item for item in cls.KEYS.items())


def main(argv: Optional[Sequence[str]] = None) -> int:
    """Open the room in a window, playing the movie named or the film made here"""
    parser = argparse.ArgumentParser(
        prog='oglc-x3d-movie', description=(__doc__ or '').split('\n')[0],
        epilog=MovieScene.help(), formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('movie', nargs='?', help='an MP4 file with an H.264 track to play '
                        'on the screens (default: the film recorded here)')
    parser.add_argument('--directory', help='where the document, its images and the film '
                        'are written (default: the user cache directory); a movie named '
                        'is copied to its "%s" directory' % NAMED)
    parser.add_argument('--remake', action='store_true', help='record the film again')
    parser.add_argument('--film', help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.movie and options.remake:
        parser.error('--remake records the film made here, and %s was named to play instead'
                     % (options.movie,))
    if options.film:                            # pragma: no cover - the film process
        return record_film(options.film)
    from OpenGLContext import testingcontext, userpaths  # noqa: PLC0415 a window only for main
    from OpenGLContext.contextdefinition import ContextDefinition  # noqa: PLC0415 a window only for main
    from OpenGLContext.events import systemtime  # noqa: PLC0415 a window only for main
    try:
        directory, film = chosen_film(
            options.directory or os.path.join(userpaths.cachedirectory(), 'x3d-movie'),
            options.movie, options.remake)
    except FilmUnavailable as err:
        print('No film to play: %s' % (err,))
        return 1
    base: Any = testingcontext.getInteractive()

    class MovieContext(base):                   # pragma: no cover - needs a window
        def OnInit(self) -> None:
            self.movies = MovieScene(directory, film)
            self.sg = self.movies.scene
            for key in MovieScene.KEYS:
                self.addEventHandler('keypress', name=key, function=self.OnKey)
            print(MovieScene.help())

        def OnKey(self, event: Any) -> None:
            said = self.movies.press(event.name, systemtime.systemTime())
            if said:
                print(said)
                self.triggerRedraw(1)

    MovieContext.ContextMainLoop(definition=ContextDefinition(
        title='OpenGLContext X3D movies', size=(1280, 720), renderer='pbr'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
