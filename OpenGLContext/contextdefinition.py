"""Definition of a Context's visual parameters"""
from vrml.vrml97 import nodetypes
from vrml import node, field, fieldtypes
from OpenGL import GL

class ContextDefinition( node.Node ):
    """Node which defines required parameters for creating a visual context

    Values of -1 generally indicate "choose the default", while
    values > -1 will explicitly request the value be set.
    """
    PROTO = 'ContextDefinition'
    size = field.newField( "size", "SFVec2f", 1, (300,300))
    title = field.newField( "title", "SFString", 1, "")
    profileFile = field.newField( "profileFile", 'SFString',1,"")

    # optional buffers...
    doubleBuffer = field.newField( "doubleBuffer", "SFBool", 1, True)

    depthBuffer = field.newField( "depthBuffer", "SFInt32", 1, -1)
    accumulationBuffer = field.newField( "accumulationBuffer", "SFInt32", 1, -1)
    stencilBuffer = field.newField( "stencilBuffer", "SFInt32", 1, 8)

    # together these define the  colour format for the buffer
    rgb = field.newField( "rgb", "SFBool", 1, True)
    alpha = field.newField( "alpha", "SFBool", 1, True)

    multisampleBuffer = field.newField( "multisampleBuffer", "SFInt32", 1, -1)
    multisampleSamples = field.newField( "multisampleSamples", "SFInt32", 1, -1)
    stereo = field.newField( "stereo", "SFInt32", 1, -1)

    debugBBox = field.newField( "debugBBox", "SFBool", 1, False )
    debugSelection = field.newField( "debugSelection", "SFBool", 1, False )

    @classmethod
    def fromConfig( cls, cfg, section='contextdefinition' ):
        """Generate a ContextDefinition from a ConfigParser instance"""
        from vrml import protofunctions
        instance = cls()
        for field in protofunctions.getFields( cls ):
            if cfg.has_option( section, field.name ):
                setattr( instance, field.name, cfg.get( section, field.name ))
        return instance

