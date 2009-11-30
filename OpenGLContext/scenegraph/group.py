"""Light-weight grouping object based on VRML 97 Group Node"""
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph import grouping

class Group(grouping.Grouping, basenodes.Group):
    """Light-weight grouping object based on VRML 97 Group Node

    The Group node provides a light-weight grouping of nodes without
    introducing a new transformation matrix (as occurs with a Transform
    node).

    Attributes of note within the Group object:

        children -- list of renderable objects
        
    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Group
    """

    