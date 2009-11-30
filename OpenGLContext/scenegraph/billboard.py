"""VRML97 Billboard-node stub"""
from vrml.vrml97 import basenodes, nodetypes
from OpenGLContext.scenegraph import grouping

class Billboard(grouping.Grouping, basenodes.Billboard):
    """Billboard node based on VRML 97 LOD

    (This is just a stub-node!)
    
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Billboard
    """
    def transform( self, mode=None, translate=1, scale=1, rotate=1 ):
        pass