"""A Text node with no FontStyle.

In a VRML97 or X3D document it is drawn with FontStyle's defaults, whose
family is SERIF (19775-1, 15.4.1); a Text built in code keeps the engine's
default face.
"""
from OpenGLContext.loaders.loader import Loader
from OpenGLContext.scenegraph.basenodes import FontStyle, Text


def test_a_documents_text_takes_fontstyles_defaults():
    scene = Loader.loads(b'<X3D version="3.3"><Scene><Shape><Text string=\'"a"\'/></Shape>'
                         b'</Scene></X3D>', 'a.x3d')
    style = scene.children[0].geometry.effectiveFontStyle()
    assert style is not None and list(style.family) == ['SERIF']


def test_text_built_in_code_keeps_the_engines_face():
    assert Text(string=['a']).effectiveFontStyle() is None


def test_a_fontstyle_given_is_used():
    style = FontStyle(family=['SANS'])
    assert Text(string=['a'], fontStyle=style).effectiveFontStyle() is style
