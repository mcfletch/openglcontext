"""Overlay HUD-style GUI layout for OpenGLContext"""
from vrml import node, field

# from OpenGLContext.scenegraph.text import glutfont
# from OpenGL.GL import *


class GUINode(object):
    """Mix-in providing basic GUI node parameters"""

    # Relative size in flex parent
    flex = field.newField("flex", "SFFloat", 1, 0)
    # When set, constrain the sizes of elements...
    width = field.newField("width", "SFFloat", 1, 1.0)
    height = field.newField("height", "SFFloat", 1, 1.0)
    # offsets from left/right of regular box
    left = field.newField("left", "SFFloat", 1, 0)
    right = field.newField("right", "SFFloat", 1, 0)
    top = field.newField("top", "SFFloat", 1, 0)
    bottom = field.newField("bottom", "SFFloat", 1, 0)

    def natural_width(self):
        """Attempt to get our natural width"""
        if self.width != 0:
            return self.width
        if hasattr(self, "calculate_width"):
            return self.calculate_width()
        return 0

    def natural_height(self):
        """Attempt to get our natural height"""
        if self.height != 0:
            return self.height
        if hasattr(self, "calculate_height"):
            return self.calculate_height()
        return 0


class PaintedImage(GUINode, node.Node):
    """Simple node holding Frame-counting values

    This node is used to hold information about the amount
    of time required to render frames for the context.
    """

    PROTO = "PaintedImage"
    image = field.newField("image", "SFImage", 1, None)

    def calculate_width(self):
        if self.image:
            # cache this...
            height = self.image.height
            width = self.image.width
            if width and height:
                if width > height:
                    return 1.0
                else:
                    return width / height
            return 1.0
        return 0

    def calculate_height(self):
        if self.image:
            height = self.image.height
            width = self.image.width
            if width and height:
                if height > width:
                    return 1.0
                else:
                    return height / width
            return 1.0
        return 0


class GUISpacer(GUINode, node.Node):
    """Used to provide a spacer for the GUI"""

    PROTO = "GUISpacer"


class GUIBox(GUINode, node.Node):
    PROTO = "GUIBox"
    children = field.NewField("children", "MFNode", 1, None)
    # support row, column
    direction = field.NewField("direction", "SFString", 1, "row")
    # support stretch, start, end, center, space-around and space-between
    flexJustify = field.NewField("flexJustify", "SFString", 1, "stretch")
