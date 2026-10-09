"""VRML97's and X3D's MovieTexture, kept with its fields and drawn without its movie

Nothing decodes a MovieTexture's ``url``. The node answers the texture
protocol a shape's appearance asks of its texture -- :meth:`cached`,
:meth:`render`, :meth:`renderPost` -- with nothing to bind, so the shape it is
on is drawn untextured. A LoadSensor watching one with a url reads it as
failed.
"""
from typing import Any, Optional

from vrml.x3d import loadsensor
from vrml.x3d import nodes as x3d

__all__ = ['MovieTexture']


class MovieTexture(x3d.MovieTexture):
    """X3D's MovieTexture, its movie not drawn"""

    def loadState(self) -> Optional[str]:
        """Failed where there is a url to read, since nothing reads it; None without one"""
        return loadsensor.FAILED if len(self.url) else None

    def cached(self, mode: Any) -> None:
        """No texture object: there is no image to bind"""
        return None

    def render(self, lit: int = 1, mode: Any = None) -> bool:
        """Binds nothing, so the appearance draws its shape untextured"""
        return False

    def renderPost(self, mode: Any = None) -> None:
        """Nothing was bound, so nothing is released"""
