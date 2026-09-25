"""A copy of a node with some of its fields changed.

A node's fields are set in place, and a node held in several places -- a
preset every lake moves by, a species a baked world names -- is changed
everywhere it is held. :class:`Varied` gives a node class :meth:`~Varied.varied`,
which answers a new node starting from this one's values, for a caller who
wants a change of its own::

    storm = CHOPPY.varied(amplitude=1.2, name='storm')
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

__all__ = ['Varied']

_Self = TypeVar('_Self', bound='Varied')


class Varied:
    """Mixin for a :class:`vrml.node.Node` class: :meth:`varied` copies."""

    if TYPE_CHECKING:
        # What the node class this is mixed into provides, with
        # vrml.node.Node.copy's signature so the two bases agree.
        def copy(self, copier: Any = None) -> Any: ...

    def varied(self: _Self, **fields: Any) -> _Self:
        """A copy of this node with ``fields`` set on it; this one is unchanged."""
        made: _Self = self.copy()
        for name, value in fields.items():
            setattr(made, name, value)
        return made
