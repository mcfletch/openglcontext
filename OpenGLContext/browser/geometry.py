from vrml import field, node
from OpenGLContext.loaders import loader
from OpenGLContext.browser import proxy
from OpenGLContext.browser.vpcurve import VPCurve

protoSG = loader.Loader.loads("""#VRML V2.0 utf8
PROTO VPSphere [
    exposedField SFRotation rotation 0,1,0 0
    exposedField SFVec3f pos 0,0,0
    exposedField SFVec3f up 0,1,0
    exposedField SFColor color 1,1,1
    exposedField SFFloat radius 1.0
] {
    Transform {
        translation IS pos
        rotation IS rotation
        children [
            Shape {
                appearance Appearance {
                    material Material {
                        diffuseColor IS color
                    }
                }
                geometry Sphere {
                    radius IS radius
                }
            }
        ]
    }
}
PROTO VPCone [
    exposedField SFRotation rotation 0,1,0 0
    exposedField SFVec3f pos 0,0,0
    exposedField SFColor color 1,1,1
    exposedField SFFloat radius 1.0
    exposedField SFFloat length 2.0
    exposedField SFVec3f positionAdjust 0,1,0
] {
    Transform {
        translation IS pos
        rotation IS rotation
        children [
            Transform {
                translation IS positionAdjust
                children [
                    Shape {
                        appearance Appearance {
                            material Material {
                                diffuseColor IS color
                            }
                        }
                        geometry Cone {
                            bottomRadius IS radius
                            height IS length
                        }
                    }
                ]
            }
        ]
    }
}
PROTO VPCylinder [
    exposedField SFRotation rotation 0,1,0 0
    exposedField SFVec3f pos 0,0,0
    exposedField SFColor color 1,1,1
    exposedField SFFloat radius 1.0
    exposedField SFFloat length 2.0
    exposedField SFVec3f positionAdjust 0,1,0
] {
    Transform {
        translation IS pos
        rotation IS rotation
        children [
            Transform {
                translation IS positionAdjust
                children [
                    Shape {
                        appearance Appearance {
                            material Material {
                                diffuseColor IS color
                            }
                        }
                        geometry Cylinder {
                            radius IS radius
                            height IS length
                        }
                    }
                ]
            }
        ]
    }
}
PROTO VPBox [
    exposedField SFRotation rotation 0,1,0 0
    exposedField SFVec3f pos 0,0,0
    exposedField SFColor color 1,1,1
    exposedField SFVec3f size 1.0,1.0,1.0
] {
    Transform {
        translation IS pos
        rotation IS rotation
        children [
            Shape {
                appearance Appearance {
                    material Material {
                        diffuseColor IS color
                    }
                }
                geometry Box {
                    size IS size
                }
            }
        ]
    }
}

""")
def _itemAccess( index, name ):
    def get_x( client ):
        return getattr( client, name)[index]
    def set_x( client, value ):
        base = getattr( client, name)
        base[index] = value
        setattr( client, name, base )
    return property( get_x,set_x, doc="""Get/Set item %i of %r for the client"""%(index,name))

class _VPColorMixIn( object ):
    """Mix-in providing color-updates"""
    red = _itemAccess( 0, 'color' )
    green = _itemAccess( 1, 'color' )
    blue = _itemAccess( 2, 'color' )
class _VPPosMixIn( object ):
    """Mix-in providing pos-updates"""
    x = _itemAccess( 0, 'pos' )
    y = _itemAccess( 1, 'pos' )
    z = _itemAccess( 2, 'pos' )
class _VPOrientMixIn( object ):
    """Mix-in providing rotation calculation"""
    axis = proxy.proxyField( 'axis', 'SFVec3f', 1, (0,1,0))

class VPSphere( _VPOrientMixIn, _VPColorMixIn, _VPPosMixIn, protoSG.protoTypes["VPSphere"] ):
    """Visual-python-style "sphere" object

    The sub-class here just adds the various convenience
    almost-fields that the VPython environment expects...
    """
class VPCone( _VPOrientMixIn, _VPColorMixIn, _VPPosMixIn, protoSG.protoTypes["VPCone"] ):
    """Visual-python-style "cone" object

    The sub-class here just adds the various convenience
    almost-fields that the VPython environment expects...
    """
class VPCylinder( _VPOrientMixIn, _VPColorMixIn, _VPPosMixIn, protoSG.protoTypes["VPCylinder"] ):
    """Visual-python-style "cylinder" object

    The sub-class here just adds the various convenience
    almost-fields that the VPython environment expects...
    """
    length = proxy.proxyField( 'length', 'SFFloat', 1, 1.0)
    def set_length( self, value, field, *args, **named ):
        """Sets height-adjustment given length"""
        self.positionAdjust = (0,value/2.0,0)
        
class VPBox( _VPOrientMixIn, _VPColorMixIn, _VPPosMixIn, protoSG.protoTypes["VPBox"] ):
    """Visual-python-style "box" object

    The sub-class here just adds the various convenience
    almost-fields that the VPython environment expects...
    """
    width = _itemAccess( 0, 'size' )
    height = _itemAccess( 1, 'size' )
    length = _itemAccess( 2, 'size' )

    