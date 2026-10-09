"""Movies played into textures the render passes sample, decoded on the GPU.

pyopengl-video reads the movie and decodes it (``pyopengl_video.playback``):
:func:`open_movie` opens one with no GL, on any thread, and a player made in a
GL context returns the texture showing the movie at a time. :class:`Playback`
is one movie playing in one context. It makes the player the first time a
frame is asked for, and copies each new frame into a :class:`FrameTexture`,
one texture per movie and context that keeps its name and its sampler for as
long as the movie plays.

The copy makes the texture what the engine's image textures are: ``GL_RGBA8``
holding sRGB values, which the PBR program decodes and the VRML97 renderers
draw as they are. pyopengl-video's own texture is ``GL_SRGB8_ALPHA8``, which
the hardware would decode a second time. ``glCopyImageSubData`` copies the
bits between the two formats on the GPU.

A context with no decoder for the movie (no backend on the machine, or a GLX
context the VA-API backend cannot import into) gets no texture. The reason is
logged once a process (:func:`report_once`), and the shape is drawn
untextured.

Needs the ``video`` extra: ``pip install OpenGLContext[video]``.
"""
from __future__ import annotations

import logging
import threading
from collections.abc import Callable, Sequence
from typing import Any, Optional

import numpy as np
from OpenGL import GL

log = logging.getLogger(__name__)

__all__ = ['FrameTexture', 'Playback', 'forget_reports', 'open_movie',
           'prepare_movie_loading', 'report_once']

#: Reasons already logged, so that each is logged once a process.
_reported: set[str] = set()
_reportedLock = threading.Lock()

#: What a movie without the package says.
NO_PACKAGE = ('MovieTexture reads movies through pyopengl-video, which is not '
              'installed (pip install OpenGLContext[video]); movies are drawn untextured')


def report_once(reason: str) -> bool:
    """Log `reason` as a warning unless it has been logged; whether it was logged now"""
    with _reportedLock:
        if reason in _reported:
            return False
        _reported.add(reason)
    log.warning('%s', reason)
    return True


def forget_reports() -> None:
    """Log each reason again the next time it is reported"""
    with _reportedLock:
        _reported.clear()


def prepare_movie_loading() -> None:
    """Make a background movie load's imports, here on the calling thread

    See :mod:`OpenGLContext.loaders.background`. A machine without
    pyopengl-video has nothing to import; the load reports that.
    """
    import OpenGLContext.loaders.loader  # noqa: F401, PLC0415 the fetch needs it
    try:
        import pyopengl_video.playback  # noqa: F401, PLC0415 the movie needs it
    except ImportError:
        pass


def _movie_class(url: Sequence[str], base: Optional[str]) -> Any:
    """pyopengl-video's Movie; ImportError where it is not installed"""
    from pyopengl_video.playback import Movie  # noqa: PLC0415 an optional package
    return Movie


def open_movie(url: Sequence[str], base: Optional[str] = None) -> Optional[tuple[Any, str]]:
    """The first entry of `url` that opens as a movie: (movie, its resolved URL)

    Each entry is resolved against `base`, the document's URL, under its
    policy (:meth:`~OpenGLContext.loaders.loader._Loader.local_copy`). Reads
    the movie's index and none of its media, with no GL. An entry that is not
    there, or not a movie pyopengl-video reads, is logged and the next is
    tried. None where none opens.
    """
    try:
        movie_class = _movie_class(url, base)
    except ImportError:
        report_once(NO_PACKAGE)
        return None
    from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 kept with its use
    for entry in url:
        try:
            resolved, path = Loader.local_copy(entry, base)
        except IOError:
            continue
        try:
            return movie_class.open(path), resolved
        except (ValueError, OSError) as err:
            log.warning('Unable to read the movie at %s: %s', resolved, err)
    return None


def _levels(size: tuple[int, int]) -> int:
    """Mipmap levels of a texture of `size`, down to one texel"""
    return max(int(size[0]), int(size[1]), 1).bit_length()


#: X3D minification filters that read no mipmaps.
_SINGLE_LEVEL = ('AVG_PIXEL', 'NEAREST_PIXEL')


class FrameTexture:
    """The texture a movie's frames are copied into, in the current context

    `size` is the movie's; `sampler` is a texture node's, as
    :func:`~OpenGLContext.scenegraph.sampler.sampler_of` gives it. Mipmaps are
    made after each copy where the sampler's minification reads them.
    Answers the texture protocol the passes ask of an image texture:
    ``texture``, ``target``, ``components``, :meth:`bind` and, for the
    fixed-function pipeline, a call.

    Raises RuntimeError where the context has no ``glCopyImageSubData``
    (OpenGL 4.3, or ``ARB_copy_image``).
    """

    target = GL.GL_TEXTURE_2D
    #: The frame is opaque.
    components = 3

    def __init__(self, size: tuple[int, int], sampler: dict[str, str]) -> None:
        from OpenGLContext.scenegraph.sampler import apply_sampler  # noqa: PLC0415 kept with its use
        if not bool(GL.glCopyImageSubData):
            raise RuntimeError('this OpenGL context has no glCopyImageSubData '
                               '(OpenGL 4.3 or ARB_copy_image) to copy a movie frame with')
        self.size = (int(size[0]), int(size[1]))
        self.mipmapped = sampler.get('minification') not in _SINGLE_LEVEL
        previous = int(GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D))
        self.texture = int(GL.glGenTextures(1))
        try:
            GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
            GL.glTexStorage2D(GL.GL_TEXTURE_2D, _levels(self.size) if self.mipmapped else 1,
                              GL.GL_RGBA8, *self.size)
            apply_sampler(self, sampler)
        finally:
            GL.glBindTexture(GL.GL_TEXTURE_2D, previous)

    def copy_from(self, source: int) -> None:
        """Copy the frame in texture `source`, of the movie's size, into this one"""
        width, height = self.size
        GL.glCopyImageSubData(source, GL.GL_TEXTURE_2D, 0, 0, 0, 0,
                              self.texture, GL.GL_TEXTURE_2D, 0, 0, 0, 0, width, height, 1)
        if self.mipmapped:
            previous = int(GL.glGetIntegerv(GL.GL_TEXTURE_BINDING_2D))
            try:
                GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
                GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
            finally:
                GL.glBindTexture(GL.GL_TEXTURE_2D, previous)

    def bind(self) -> FrameTexture:
        """Bind the texture to ``GL_TEXTURE_2D`` on the active unit"""
        GL.glBindTexture(GL.GL_TEXTURE_2D, self.texture)
        return self

    def __call__(self) -> FrameTexture:
        """Bind the texture and switch the fixed-function texture unit on"""
        self.bind()
        GL.glEnable(GL.GL_TEXTURE_2D)
        return self

    def close(self) -> None:
        """Delete the texture"""
        if self.texture:
            GL.glDeleteTextures(1, np.array([self.texture], dtype=np.uint32))
            self.texture = 0


def _player(movie: Any) -> Any:
    """pyopengl-video's player for `movie` in the current context"""
    return movie.player()


class Playback:
    """One movie playing into one texture in one GL context

    movie -- a pyopengl-video ``Movie``
    sampler -- the texture node's sampler (``sampler_of``)
    make_player -- the player for the movie in the current context;
        ``movie.player()`` by default
    make_target -- the texture frames are copied into, from the movie's size
        and the sampler; :class:`FrameTexture` by default

    A player that cannot be made, a target that cannot, or a decoder that
    raises, ends the playback: :meth:`texture` answers None from then on and
    the reason is logged once a process.
    """

    def __init__(self, movie: Any, sampler: dict[str, str], *,
                 make_player: Callable[[Any], Any] = _player,
                 make_target: Callable[[tuple[int, int], dict[str, str]], Any] = FrameTexture,
                 ) -> None:
        self.movie = movie
        self.sampler = sampler
        self._makePlayer = make_player
        self._makeTarget = make_target
        self.player: Any = None
        self.target: Any = None
        #: Why the movie is not drawn, or None while it is.
        self.failed: Optional[str] = None
        self._shown: Optional[int] = None

    def texture(self, seconds: float) -> Any:
        """The texture showing the movie at `seconds`; None where it is not drawn"""
        if self.failed is not None:
            return None
        try:
            if self.player is None:
                self.player = self._makePlayer(self.movie)
                self.target = self._makeTarget(tuple(self.movie.size), self.sampler)
            source = self.player.frame_at(float(seconds))
            if self.player.frame != self._shown:
                self.target.copy_from(source)
                self._shown = self.player.frame
        except (RuntimeError, ValueError, GL.GLError) as err:
            # pyopengl-video's VideoError is a RuntimeError, and a stream it
            # cannot parse is a ValueError.
            self._fail(str(err))
            return None
        return self.target

    def _fail(self, reason: str) -> None:
        self.failed = reason
        report_once('A MovieTexture is drawn untextured: %s' % (reason,))
        self.close()

    def close(self) -> None:
        """Close the player and delete the texture, in the current context"""
        player, self.player = self.player, None
        target, self.target = self.target, None
        if player is not None:
            player.close()
        if target is not None:
            target.close()
        self._shown = None
