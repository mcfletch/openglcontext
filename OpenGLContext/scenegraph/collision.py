"""Non-functional Collision node to allow loading content using the node"""
from vrml.vrml97 import basenodes
from OpenGLContext.scenegraph import grouping

class Collision(grouping.Grouping, basenodes.Collision):
    """Collision node based on VRML 97 Collision

    Note: at the moment this doesn't actually do anything
    beyond what a regular group does.  It's just here to
    let content that uses a Collision be visible.

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Collision
    """