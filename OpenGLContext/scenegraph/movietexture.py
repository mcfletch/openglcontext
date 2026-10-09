"""X3D's and VRML97's MovieTexture: a movie decoded on the GPU, shown at its media time

The node's timing is pyvrml97's (:mod:`vrml.x3d.media`), on the engine's clock
and polled by each context it is bound to, as a TimeSensor is: `startTime`,
`stopTime`, `pauseTime`, `resumeTime`, `loop` and `speed`, a negative speed
running the movie backwards. :meth:`MovieTexture.position` is the media time
shown:

- before the movie first plays, its first frame, or its last for a negative
  `speed`;
- while it plays, the frame for its time, wrapping where `loop` is true;
- while it is paused, and once it has stopped, the frame it was showing.

Setting `url` opens the movie on the engine's loader pool
(:mod:`OpenGLContext.loaders.background`), each entry resolved against the
document under its policy (:meth:`~OpenGLContext.loaders.loader._Loader.local_copy`),
and records the load state a LoadSensor reads. The movie's length is sent as
`duration_changed` on the render thread; -1 where no entry opens.

Each context draws the movie through a
:class:`~OpenGLContext.video.playback.Playback`, made the first time a shape
wearing the texture is drawn there: the decoder's frame for the media time,
copied into one texture with the node's `repeatS`, `repeatT` or
`textureProperties` sampler. Those fields are read when the playback is made,
as X3D gives them ``initializeOnly``. A context with no decoder for the movie
draws its shapes untextured, and the reason is logged once
(:func:`~OpenGLContext.video.playback.report_once`).

Being drawn binds the node to the context, so a movie whose shapes are never
drawn sends no events. Its media time is the same whenever it is first drawn:
a run starts at `startTime`, not at the first poll.

pyopengl-video decodes video and no audio, so a MovieTexture used as a
``Sound`` node's ``source`` is silent.
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Optional

from vrml import fieldtypes, protofunctions
from vrml.x3d import loadsensor, media

from OpenGLContext import contextresources
from OpenGLContext.scenegraph.imagetexture import URLRead
from OpenGLContext.scenegraph.sampler import sampler_of
from OpenGLContext.scenegraph.x3druntime import EngineTimed, Polled
from OpenGLContext.video import playback

__all__ = ['MovieTexture', 'MovieURLField']



def _close(shown: Any) -> None:
    """Close a playback, in the context that made it"""
    shown.close()


#: Each node's playback in each context, closed in the context that made it:
#: the entries are playbacks rather than names, and closing one deletes its.
_PLAYBACKS = contextresources.ContextNames('_moviePlaybacks', _close)

#: What a load that opened nothing leaves for the render thread.
_FAILED = object()


class MovieURLField(fieldtypes.MFString):
    """A MovieTexture's `url`: setting it opens the movie in the background"""

    fieldType = 'MFString'

    def __set__(self, client: Any, value: Any, notify: bool = True) -> Any:
        value = super().fset(client, value, notify=True)
        client.requestImage()
        return value

    fset = __set__


class MovieTexture(URLRead, Polled, EngineTimed, media.MovieTexture):
    """X3D's MovieTexture, decoded through pyopengl-video

    Reference:
        https://www.web3d.org/specifications/X3Dv4/ISO-IEC19775-1v4-IS/Part01/components/texturing.html#MovieTexture
    """

    url = MovieURLField('url', 1, list)
    READ_FIELD = '_movie'
    prepareRead = staticmethod(playback.prepare_movie_loading)

    # ------------------------------------------------------------- loading

    def loadBackground(self, url: Any, contexts: Sequence[Any] = ()) -> None:
        """Open the first entry of `url` that is a movie; on a loader thread"""
        root = protofunctions.root(self)
        found = playback.open_movie(
            [str(entry) for entry in ([url] if isinstance(url, str) else url)],
            getattr(root, 'baseURI', None) if root else None)
        self.__dict__['_arrived'] = _FAILED if found is None else found[0]
        loadsensor.set_load_state(self, loadsensor.FAILED if found is None
                                  else loadsensor.LOADED)
        for reference in contexts:
            found_context = reference()
            if found_context is not None:
                found_context.triggerRedraw(1)

    def adoptMovie(self) -> bool:
        """Take the movie the last load opened, sending `duration_changed`; whether one arrived"""
        arrived = self.__dict__.pop('_arrived', None)
        if arrived is None:
            return False
        if arrived is _FAILED:
            self.__dict__.pop('_movie', None)
            self.__dict__.pop('_duration', None)
            self.duration_changed = -1.0
        else:
            self.__dict__['_movie'] = arrived
            self.setDuration(arrived.duration)
        return True

    def movie(self) -> Any:
        """The pyopengl-video ``Movie`` playing, or None"""
        return self.__dict__.get('_movie')

    # ------------------------------------------------------------- timing

    def advance(self, now: float) -> bool:
        """Take an arrived movie, then run the clock to `now`; whether anything was sent"""
        adopted = self.adoptMovie()
        return bool(super().advance(now)) or adopted

    def bind(self, context: Any) -> bool:
        """Be polled by `context`'s time manager; advanced to now the first time"""
        manager = context.getTimeManager()
        polled = self.__dict__.get('_polledBy')
        fresh = polled is None or manager not in polled
        super().bind(context)
        if fresh:
            self.advance(self.now())
        return True

    # ------------------------------------------------------------- drawing

    def cached(self, mode: Any = None) -> Any:
        """The texture showing the movie's frame in this context; None where none is drawn"""
        found_context = getattr(mode, 'context', None)
        if found_context is not None and hasattr(found_context, 'getTimeManager'):
            self.bind(found_context)
        self.adoptMovie()
        movie = self.movie()
        if movie is None:
            return None
        entries = _PLAYBACKS.entries(self)
        if entries is None:
            return None
        shown = entries.get('movie')
        if shown is None or shown.movie is not movie:
            if shown is not None:
                shown.close()
            shown = entries['movie'] = playback.Playback(
                movie, sampler_of(self, tuple(movie.size)))
        return shown.texture(self.position())

    def imageSize(self) -> Optional[tuple[int, int]]:
        """The movie's (width, height); None before it is open"""
        movie = self.movie()
        return None if movie is None else (int(movie.size[0]), int(movie.size[1]))

    def hasAlpha(self) -> bool:
        """A movie frame is opaque"""
        return False

    def transparent(self, mode: Any = None) -> int:
        """A movie frame is opaque"""
        return 0

    def render(self, visible: int = 1, lit: int = 1, mode: Any = None) -> Optional[int]:
        """Bind the frame for an appearance; falsy, the frame being opaque

        The fixed-function pipeline's texture unit is switched on; under a
        shader the frame is bound for the program to sample.
        """
        if not visible:
            return None
        texture = self.cached(mode)
        if texture is None:
            return None
        if getattr(mode, 'shader_mode', False):
            texture.bind()
        else:
            texture()
        return 0

    def renderPost(self, mode: Any = None) -> None:
        """Switch the fixed-function texture unit off again"""
        if getattr(mode, 'shader_mode', False) or self.movie() is None:
            return
        from OpenGL import GL  # noqa: PLC0415 only the fixed-function pipeline asks
        GL.glDisable(GL.GL_TEXTURE_2D)
