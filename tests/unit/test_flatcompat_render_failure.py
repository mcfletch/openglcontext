"""A node that raises while drawing costs its own draw, not the application.

The compatibility pass records the failure through
:meth:`~OpenGLContext.passes._flat.FlatPass.renderFailed`, exactly as the core
pass does, and goes on to the next shape.
"""
from typing import Any, List, Tuple

import pytest


class _Raiser:
    """A renderable whose draw always fails."""

    pickable = False

    def Render(self, mode: Any = None, **named: Any) -> None:
        raise ValueError('this node cannot draw')

    def RenderTransparent(self, mode: Any = None, **named: Any) -> None:
        raise ValueError('this node cannot draw')


class _Drawn:
    """A renderable that records that it was asked to draw."""

    pickable = False

    def __init__(self) -> None:
        self.drawn = 0

    def Render(self, mode: Any = None, **named: Any) -> None:
        self.drawn += 1

    def RenderTransparent(self, mode: Any = None, **named: Any) -> None:
        self.drawn += 1


class _Definition:
    debugBBox = False


class _Context:
    contextDefinition = _Definition()


def _records(nodes: List[Any], transparent: int) -> List[Tuple[Any, ...]]:
    """One (sortKey, mvmatrix, tmatrix, bvolume, path) record per node."""
    from OpenGLContext.arrays import identity
    matrix = identity(4, 'f')
    return [((transparent, 0.0), matrix, matrix, None, [node]) for node in nodes]


@pytest.fixture
def compat_pass(gl_context_compat: Any) -> Any:
    from OpenGLContext.passes.flatcompat import FlatPass
    pass_object = FlatPass.__new__(FlatPass)
    pass_object.context = _Context()
    pass_object.failed: List[Tuple[str, Any, BaseException]] = []

    def renderFailed(where: str, node: Any, err: BaseException) -> None:
        pass_object.failed.append((where, node, err))

    pass_object.renderFailed = renderFailed
    pass_object._deferredTransparent = []
    return pass_object


class TestOpaqueFailure:
    def test_the_rest_of_the_scene_still_draws(self, compat_pass: Any) -> None:
        good = _Drawn()
        compat_pass.renderOpaque(_records([_Raiser(), good], transparent=0))
        assert good.drawn == 1

    def test_the_failure_is_recorded(self, compat_pass: Any) -> None:
        compat_pass.renderOpaque(_records([_Raiser()], transparent=0))
        assert [where for where, _node, _err in compat_pass.failed] == ['opaque']
        assert isinstance(compat_pass.failed[0][2], ValueError)


class TestTransparentFailure:
    def test_the_rest_of_the_scene_still_draws(self, compat_pass: Any) -> None:
        good = _Drawn()
        compat_pass.renderTransparent(_records([_Raiser(), good], transparent=1))
        assert good.drawn == 1

    def test_the_failure_is_recorded(self, compat_pass: Any) -> None:
        compat_pass.renderTransparent(_records([_Raiser()], transparent=1))
        assert [where for where, _node, _err in compat_pass.failed] == ['transparent']
