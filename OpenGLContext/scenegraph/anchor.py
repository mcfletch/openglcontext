"""X3D's and VRML97's Anchor: a group whose geometry, clicked, follows its url

The Anchor is reached by the pointer as the pointing-device sensors are
(:mod:`OpenGLContext.scenegraph.x3dpointing`): pressing the primary button
over its geometry and releasing it there calls
``context.OnAnchor(anchor, url, parameter)``, which the context answers
(:meth:`OpenGLContext.context.ContextCore.OnAnchor`).
"""
from typing import Any, Optional

from vrml.vrml97 import basenodes

from OpenGLContext.scenegraph import grouping


class Anchor(grouping.Grouping, basenodes.Anchor):
    """A group that follows its url when its geometry is clicked

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/networking.html#Anchor
    """

    def bind(self, context: Any) -> bool:
        """Have `context`'s pointer reach this Anchor"""
        from OpenGLContext.scenegraph import x3dpointing
        x3dpointing.sensing(context)
        return True

    # The pointer, as x3dpointing.PointerSensing tells a sensor of it.

    def pointerOver(self, hit: Optional[Any]) -> None:
        """The pointer has moved over the Anchor's geometry or off it"""

    def pointerPress(self, hit: Any, ray: Any) -> None:
        """The button has gone down over the Anchor's geometry"""

    def pointerDrag(self, hit: Optional[Any], ray: Any) -> None:
        """The pointer has moved with the button held"""

    def follow(self, context: Any) -> Any:
        """Ask `context` to follow this Anchor's url"""
        return context.OnAnchor(self, list(self.url), list(self.parameter))
