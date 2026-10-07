"""X3D's ViewpointGroup: viewpoints listed together, and where they are listed

The group's viewpoints are the scene's as any others are. The next-viewpoint
key (:func:`OpenGLContext.passes.viewpointbinding.next_viewpoint`) passes over
those of a group that is not `displayed`, or that has a `size` and the viewer
is outside the box of that size about its `center`.
"""
from typing import Any

import numpy as np
from vrml.vrml97 import nodetypes
from vrml.x3d import nodes as x3d


class ViewpointGroup(x3d.ViewpointGroup):
    """X3D's ViewpointGroup

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/navigation.html#ViewpointGroup
    """

    def renderedChildren(
        self, types: Any = (nodetypes.Children, nodetypes.Rendering,)
    ) -> list[Any]:
        """The group's viewpoints and the groups within it"""
        return list(self.children)

    def lists(self, viewer: Any) -> bool:
        """Whether the group's viewpoints are offered to a viewer at `viewer`

        `viewer` is a point in the group's coordinates.
        """
        if not self.displayed:
            return False
        size = np.asarray(self.size, dtype=np.float64)
        if not np.all(size > 0):
            return True
        offset = np.abs(np.asarray(viewer, np.float64)[:3] - np.asarray(self.center, np.float64))
        return bool(np.all(offset <= size / 2.0))
