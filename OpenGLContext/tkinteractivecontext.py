"""Interactive context using the Tk API (provides navigation support)"""

from OpenGLContext import interactivecontext, tkcontext
from OpenGLContext.move import viewplatformmixin


class TkInteractiveContext(
    viewplatformmixin.ViewPlatformMixin,
    interactivecontext.InteractiveContext,
    tkcontext.TkContext,
):
    """Tk context providing camera, mouse and keyboard interaction"""


if __name__ == "__main__":
    from OpenGLContext.scenegraph.basenodes import Box, Shape, sceneGraph

    class TestRenderer(TkInteractiveContext):
        def OnInit(self):
            self.sg = sceneGraph(children=[Shape(geometry=Box(size=(2, 2, 2)))])

        def getSceneGraph(self):
            return self.sg

    TestRenderer.ContextMainLoop()
