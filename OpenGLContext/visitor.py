"""Finding nodes of a given type in a scenegraph.

:func:`find` walks a scenegraph the way the renderer does -- following each node's
``renderedChildren`` -- and returns a
:class:`~OpenGLContext.scenegraph.nodepath.NodePath` to every node of the types
asked for. Because the traversal is the rendering traversal, a node the renderer
would not reach is not found either; that is the point, since callers are looking
for bindables (Viewpoint, Background, Fog, NavigationInfo) which only mean
something where the renderer would encounter them.
"""
import traceback
from vrml.vrml97 import nodetypes
from vrml import node as _node
from OpenGLContext.scenegraph import nodepath
import logging

log = logging.getLogger(__name__)

#: Node types whose children are followed during a traversal.
TRAVERSAL_TYPES = (nodetypes.Traversable, nodetypes.Children,
                   _node.PrototypedNode, nodetypes.Rendering)


def children(node, types=TRAVERSAL_TYPES):
    """The children of ``node`` to traverse into, or ``()`` when it has none."""
    if hasattr(node, 'renderedChildren'):
        return node.renderedChildren(types)
    return ()


def find(sg, desiredTypes=()):
    """Node-paths to every instance of ``desiredTypes`` within scenegraph ``sg``.

    ``desiredTypes`` may be a single type or a sequence of them. Returns a list of
    :class:`NodePath` objects, each the route from ``sg`` down to a matching node.

    Note:
        The traversal is the one the rendering procedure uses, so a non-rendering
        node can legitimately be missed by the search.
    """
    if not isinstance(desiredTypes, tuple):
        desiredTypes = (desiredTypes,)
    result = []
    # An explicit stack rather than recursion, so depth is bounded by memory
    # rather than by the interpreter's recursion limit. ``index`` records the
    # depth each queued node hangs at, which is what lets one flat list
    # reconstruct the full path to every match.
    todo = [(0, sg)]
    currentStack = []
    childrenTypes = TRAVERSAL_TYPES + desiredTypes
    while todo:
        index, current = todo.pop(0)
        del currentStack[index:]
        is_desired = isinstance(current, desiredTypes)
        try:
            found = children(current, types=childrenTypes)
        except Exception:
            traceback.print_exc()
            log.error("""exception in children method for node %s""", current)
            continue
        new_items = [(len(currentStack) + 1, child) for child in found]
        if is_desired or new_items:
            currentStack.append(current)
            if is_desired:
                result.append(nodepath.NodePath(tuple(currentStack)))
            if new_items:
                todo[0:0] = new_items
    return result
