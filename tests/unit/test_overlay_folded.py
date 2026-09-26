"""Every context has the overlay stack.

``OverlayStackMixin`` is one of :class:`~OpenGLContext.context.Context`'s
bases, ahead of the views and the navigation, so a panel is offered each event
first.  ``OverlayMixin`` is the name applications mixed in ahead of
``Context``; it stays a class a program can still list, which adds nothing and
says so.
"""
import warnings

import pytest

from OpenGLContext.context import Context
from OpenGLContext.multiview.mixin import MultiViewMixin
from OpenGLContext.move.viewplatformmixin import ViewPlatformMixin
from OpenGLContext.ui.overlay import OverlayMixin, OverlayStack, OverlayStackMixin


def test_every_context_has_the_overlay_stack():
    assert issubclass(Context, OverlayStackMixin)


def test_the_overlay_is_offered_events_before_the_views_and_the_navigation():
    order = Context.__mro__
    assert order.index(OverlayStackMixin) < order.index(MultiViewMixin) \
        < order.index(ViewPlatformMixin)


def test_a_context_made_with_no_window_has_a_stack_to_push_onto():
    context = Context.__new__(Context)
    assert isinstance(context.overlays, OverlayStack)


def test_a_class_still_listing_overlaymixin_is_built_and_told():
    with pytest.warns(DeprecationWarning, match='OverlayMixin'):
        class Listed(OverlayMixin, Context):
            pass
    assert Listed.__mro__.index(OverlayStackMixin) > Listed.__mro__.index(Context)


def test_the_stack_is_the_same_one_either_way():
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', DeprecationWarning)

        class Listed(OverlayMixin, Context):
            pass
    assert Listed.overlays is Context.overlays
