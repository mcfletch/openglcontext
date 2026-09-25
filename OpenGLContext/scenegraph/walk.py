"""Every node reachable from a root, each once.

A scenegraph may share a subtree between several parents, and a file may
refer back to a node above the one referring to it, so a plain recursive walk
counts a shared node once per parent and does not finish on a cycle.
:func:`reachable` visits each node once, however many ways there are to it,
and uses an explicit stack, so how deep a loaded scene goes is bounded by
memory rather than by the interpreter's recursion limit.

    from OpenGLContext.scenegraph.walk import reachable

    lights = [node for node in reachable(scene) if isinstance(node, Light)]
    meshes = reachable(model, fields=('children', 'geometry'))
"""
from typing import Any, Dict, Iterator, List, Sequence

__all__ = ['reachable']


def reachable(root: Any, fields: Sequence[str] = ('children',)) -> Iterator[Any]:
    """Yield ``root`` and every node reachable from it through ``fields``.

    Depth first, a parent before its children and children in field order,
    each node once. A field may hold one node or a sequence of them; a node
    without the field, or with ``None`` in it, has nothing further there.
    """
    # Each node visited, by address, holding the node so that the address
    # is not handed to another object while the walk is suspended.
    seen: Dict[int, Any] = {}
    stack = [root]
    while stack:
        node = stack.pop()
        if id(node) in seen:
            continue
        seen[id(node)] = node
        yield node
        below: List[Any] = []
        for field in fields:
            value = getattr(node, field, None)
            if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
                below.extend(value)
            elif value is not None:
                below.append(value)
        stack.extend(reversed(below))
