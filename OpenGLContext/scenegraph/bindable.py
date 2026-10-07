"""Which of a scene's backgrounds or fogs the render pass uses

X3D binds the node on top of its scene's stack (:mod:`vrml.x3d.binding`). The
engine's own backgrounds and :class:`~OpenGLContext.scenegraph.fog.Fog` also
have a ``bound`` field, set where a scene is built: where no path reaches the
stack, the first whose node has it set is bound, before the first path.
"""
from collections.abc import Sequence
from typing import Any

from vrml import field
from vrml.x3d import binding

__all__ = ['bound_field', 'current_path']


def bound_field() -> Any:
    """The ``bound`` field: this node is the one to bind where none is"""
    return field.newField('bound', 'SFBool', 1, 0)


def current_path(paths: Sequence[Any]) -> Any:
    """The path to the bound node of `paths`, binding one where none is

    The stack's choice where a path reaches it; else the first path whose
    node's ``bound`` is set; else the first path. None where `paths` is empty.
    """
    ordered = sorted(paths, key=lambda path: not getattr(path[-1], 'bound', False))
    return binding.current_path(ordered)
