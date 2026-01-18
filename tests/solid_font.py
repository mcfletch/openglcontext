#! /usr/bin/env python
'''Low-level tests of solid fonts

Tests solid 3D font rendering using the scenegraph with Transform nodes.
This approach works in both core and compatibility OpenGL profiles.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGLContext.scenegraph.basenodes import *

## The following makes the toolsfont provider available, toolsfont is dependent
## on the Python fonttools module, which is a cross-platform TTF-file module.
from OpenGLContext.scenegraph.text import toolsfont, fontstyle3d
## The fontprovider.FontProvider class provides the hook for getting a particular
## font-provider implementation
from OpenGLContext.scenegraph.text import fontprovider
MESSAGE = u"The quick brown fox jumped over the lazy dog"

class TestContext( BaseContext ):
    """Test context for solid fonts using scenegraph."""
    initialPosition = (0, 0, 10)  # Camera position to see the text

    def OnInit(self):
        """Set up the scenegraph with text"""
        print("""You should see a 3D-rendered text message""")
        print('  <n> next fontstyle')
        self.addEventHandler( "keypress", name="n", function = self.OnNextStyle)
        providers = fontprovider.getProviders( 'solid' )
        if not providers:
            raise ImportError( """No solid font providers registered! Demo won't function properly!""" )
        registry = self.getTTFFiles()
        styles = []
        for font in registry.familyMembers( 'SANS' ):
            names = registry.fontMembers( font, 400, 0)
            for name in names:
                styles.append( fontstyle3d.FontStyle3D(
                    family = [name],
                    size = .3,
                    justify = "MIDDLE",
                    thickness = .25,
                    quality = 3,
                    renderSides = 1,
                    renderFront = 1,
                    renderBack = 1,
                ))
        self.styles = styles
        self.currentStyle = 0
        self.buildSceneGraph()

    def buildSceneGraph(self):
        """Build the scenegraph with the current font style"""
        style = self.styles[self.currentStyle]

        # Create text node with current style
        self.textNode = Text(
            string=[MESSAGE],
            fontStyle=style,
        )

        # Create scenegraph with transform
        # Translation of (0, 0, 3) and rotation of 80 degrees around Y axis
        self.sg = sceneGraph(
            children=[
                Transform(
                    translation=(0, 0, 3),
                    rotation=(0, 1, 0, 1.396),  # ~80 degrees in radians
                    children=[
                        Shape(
                            appearance=Appearance(
                                material=Material(
                                    diffuseColor=(0.8, 0.8, 0.8),
                                ),
                            ),
                            geometry=self.textNode,
                        ),
                    ],
                ),
                # Add a light so we can see the text
                DirectionalLight(
                    direction=(0.5, -1, -0.5),
                    intensity=1.0,
                ),
            ],
        )

    def OnNextStyle( self, event = None):
        """Advance to the next font style"""
        self.currentStyle = (self.currentStyle + 1) % len(self.styles)
        print("New font style: %r"%( self.styles[self.currentStyle],))
        self.buildSceneGraph()
        self.triggerRedraw( 1 )


if __name__ == "__main__":
    TestContext.ContextMainLoop()
