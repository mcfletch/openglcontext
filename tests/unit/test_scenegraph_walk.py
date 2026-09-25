"""Every node reachable from a root, each once: :mod:`OpenGLContext.scenegraph.walk`."""
from OpenGLContext.scenegraph.walk import reachable


class _Node:
    def __init__(self, name, *children, geometry=None):
        self.name = name
        self.children = list(children)
        self.geometry = geometry


def _names(nodes):
    return [node.name for node in nodes]


def test_a_parent_comes_before_its_children_in_order():
    tree = _Node('root', _Node('a', _Node('a1')), _Node('b'))
    assert _names(reachable(tree)) == ['root', 'a', 'a1', 'b']


def test_a_shared_subtree_is_visited_once():
    shared = _Node('shared', _Node('leaf'))
    tree = _Node('root', _Node('left', shared), _Node('right', shared))
    assert _names(reachable(tree)) == ['root', 'left', 'shared', 'leaf', 'right']


def test_a_cycle_ends():
    top = _Node('top')
    top.children.append(_Node('below', top))
    assert _names(reachable(top)) == ['top', 'below']


def test_a_field_holding_one_node_is_followed():
    mesh = _Node('mesh')
    tree = _Node('root', _Node('shape', geometry=mesh))
    assert _names(reachable(tree, fields=('children', 'geometry'))) == [
        'root', 'shape', 'mesh']


def test_only_the_named_fields_are_followed():
    tree = _Node('root', _Node('shape', geometry=_Node('mesh')))
    assert _names(reachable(tree)) == ['root', 'shape']


def test_something_with_none_of_the_fields_is_the_whole_walk():
    thing = object()
    assert list(reachable(thing)) == [thing]


def test_depth_is_not_bounded_by_the_recursion_limit():
    node = top = _Node(0)
    for depth in range(1, 5000):
        child = _Node(depth)
        node.children.append(child)
        node = child
    assert sum(1 for _ in reachable(top)) == 5000
