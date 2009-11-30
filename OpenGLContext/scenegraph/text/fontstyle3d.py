"""FontStyle extensions for OpenGLContext"""
from vrml.vrml97 import basenodes
from vrml import field, node

class FontStyle( basenodes.FontStyle ):
    """FontStyle with ability to specify geometry format"""
    PROTO = 'FontStyle'
##	#Fields
##	style = field.newField( 'style', 'SFString', 0, 'PLAIN')
##	topToBottom = field.newField( 'topToBottom', 'SFBool', 0, 1)
##	family = field.newField( 'family', 'MFString', 0, 'SERIF')
##	language = field.newField( 'language', 'SFString', 0, '')
##	horizontal = field.newField( 'horizontal', 'SFBool', 0, 1)
##	justify = field.newField( 'justify', 'MFString', 0, ['BEGIN'])
##	spacing = field.newField( 'spacing', 'SFFloat', 0, 1.0)
##	leftToRight = field.newField( 'leftToRight', 'SFBool', 0, 1)
##	size = field.newField( 'size', 'SFFloat', 0, 1.0)
    format = field.newField( 'format', 'SFString', 1, "solid")

class FontStyle3D( FontStyle ):
    """FontStyle with ability to specify 3D extrusion properties"""
    PROTO = 'FontStyle3D'
    quality = field.newField( 'quality', 'SFInt32', 1, 3)
    renderFront = field.newField( 'renderFront', 'SFBool', 1, 1)
    renderSides = field.newField( 'renderSides', 'SFBool', 1, 0)
    renderBack = field.newField( 'renderBack', 'SFBool', 1, 0)
    thickness = field.newField( 'thickness', 'SFFloat', 1, 0.0)

class Glyph( node.Node ):
    """Storage for a glyph's data"""
    PROTO = "Glyph"

class Glyph3D( Glyph ):
    """Storage for a 3D glyph's data"""
    PROTO = "Glyph3D"
    character = field.newField( 'character', 'SFString', 1, "")
    width = field.newField( 'width', 'SFFloat', 1, 0.0)
    height = field.newField( 'height', 'SFFloat', 1, 0.0)
    contours = field.newField( 'contours', 'MFVec2f', 1, list)
    outlines = field.newField( 'outlines', 'MFVec2f', 1, list)

class SolidGlyph3D( Glyph3D ):
    """Storage for a solid 3D glyph's data"""
    extrusionData = field.newField( 'extrusionData', 'MFNode', 1, list)
    tessellationData = field.newField( 'tessellationData', 'MFNode', 1, list)
class SG3D_ExtrData( node.Node ):
    """Storage for contour's extrusion-data for a SolidGlyph3D"""
    PROTO = "SG3D_ExtrData"
    points = field.newField( 'points', 'MFVec2f', 1, list)
    normals = field.newField( 'normals', 'MFVec2f', 1, list)
class SG3D_TessData( node.Node ):
    """Storage for face-tessellation-data for a SolidGlyph3D"""
    PROTO = "SG3D_TessData"
    geometryType = field.newField( 'geometryType', 'SFString', 1, "GL_TRIANGLES")
    vertices = field.newField( 'vertices', 'MFVec2f', 1, list)

class Font( node.Node ):
    """Storage for a precompiled Font"""
    PROTO = "Font"
    glyphs = field.newField( 'glyphs', 'MFNode', 1, list)
    style = field.newField( 'style', 'SFNode', 1, None)
    