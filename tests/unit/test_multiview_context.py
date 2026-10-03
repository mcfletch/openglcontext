"""A MultiViewContext shows the quad arrangement without being asked."""
from OpenGLContext.context import Context, MultiViewContext


def test_base_class_alone_gives_four_views(scene_context):
    with scene_context([], base=MultiViewContext) as context:
        assert context.views is not None
        assert context.views.mode == 'quad'
        assert len(context.views.views) == 4


def test_a_plain_context_has_no_views(scene_context):
    with scene_context([], base=Context) as context:
        assert getattr(context, 'views', None) is None


def test_setupviews_is_the_override_point(scene_context):
    class Plan(MultiViewContext):
        calls = 0

        def setupViews(self):
            Plan.calls += 1
            self.startViews(arrangement='single', chrome=False)

    with scene_context([], base=Plan) as context:
        assert Plan.calls == 1
        assert context.views.mode == 'single'
        assert context.viewChrome is None


def test_views_the_navigation_declares_are_not_set_up_again(scene_context):
    from OpenGLContext.move.navigationdefinition import Navigation
    from OpenGLContext.multiview.mixin import quadViews

    class Counted(MultiViewContext):
        calls = 0

        def setupViews(self):
            Counted.calls += 1
            super().setupViews()

    declared = Navigation(modes=['examine'], views=quadViews(arrangement='single'))
    with scene_context([], base=Counted, navigation=declared) as context:
        assert Counted.calls == 0
        assert context.views.mode == 'single'
