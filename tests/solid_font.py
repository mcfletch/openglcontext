#! /usr/bin/env python
'''=3D text=

[solid_font.py-screen-0001.png Screenshot]

Text with depth: the glyphs of an installed font, turned into triangles and
given a thickness.  It is the same work as any other swept shape -- a
closed outline tessellated into a face, and the outline swept to make the
sides -- with the outlines coming from the font file rather than from a
list of points.

`Text` is the VRML97 node and `FontStyle3D` says how to build it:

    family       which installed font, by name
    size         how tall a line is, in scene units
    thickness    how far the glyphs are extruded
    quality      how finely a curved edge is subdivided
    justify      where the string sits against its origin
    renderFront, renderBack, renderSides
                 which of the three surfaces to build

The fonts are the ones on the machine.  ``fontprovider.getProviders``
answers which providers are registered; the ``toolsfont`` provider reads
TrueType outlines through `ttfquery`, and the registry it builds is what
``getTTFFiles`` below returns.  :doc:`The text page </text>` covers the
flat text nodes beside these, and :doc:`Tessellation </tessellation>` is
the outline-to-triangles step on its own.

Keys:

    n       the next installed font
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
                # Point light above and to the right of the camera
                # (camera is at initialPosition (0, 0, 10), looking down -Z),
                # placed slightly behind it so it lights from over the shoulder.
                PointLight(
                    location=(5, 5, 12),
                    intensity=1.0,
                ),
                # Dim, faintly-blue fill to the left, down and forward (beyond
                # the text in -Z) so it backlights the text away from the camera.
                PointLight(
                    location=(-15, -6, 0),
                    color=(0.9, 0.9, 1.0),
                    intensity=0.7,
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
