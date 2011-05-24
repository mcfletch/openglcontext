"""Standard Light-node types"""
from OpenGL.GL import *
from math import pi
from vrml.vrml97 import basenodes, nodetypes
from vrml.vrml97 import transformmatrix
from vrml import node
from OpenGLContext.arrays import array, dot, identity
from OpenGLContext import vectorutilities

class Light(object ):#nodetypes.Light, nodetypes.Children, node.Node ):
    """Abstract base class for all lights

    attributes:
        pointSource -- whether or not we are a point
            light source, stored as a float value, if
            false, the light is a directional light

        location -- the object-space location of point-source
            lights (i.e. non-directional)

            or

        direction -- direction a directional or spotlight
            is shining

        color -- light diffuse color

        ambientIntensity -- ambient light fraction of color
    """
    pointSource = 1.0
    def Light( self, lightID, mode=None ):
        """Render light using given light ID for the given mode

        This will check for:
            mode.lighting
            mode.lightingAmbient
            mode.lightingDiffuse
        and appropriately enable/disable the various features.

        Returns whether or not the light ID has been used,
        which allows us to reuse the light ID in case this
        light does not actually need it for this particular
        rendering pass.
        """
        if self.on and mode.lighting and (mode.lightingAmbient or mode.lightingDiffuse):
            glEnable( GL_LIGHTING )
            glEnable( lightID )
            ### The following code allows for ambient-only lighting
            ### and/or diffuse-only
            if mode.lightingAmbient:
                x,y,z = self.color * self.ambientIntensity
            else:
                x,y,z = 0.0, 0.0, 0.0
            glLightfv(lightID, GL_AMBIENT, array((x,y,z,1.0),'f'))

            if mode.lightingDiffuse:
                x,y,z = self.color
            else:
                x,y,z = 0.0, 0.0, 0.0
            glLightfv(
                lightID,
                GL_DIFFUSE,
                array((x,y,z,1.0),'f')*self.intensity
            )
            if hasattr( self, 'location' ):
                x,y,z = self.location
            else:
                x,y,z = -self.direction
            glLightfv(lightID, GL_POSITION, array((x,y,z,self.pointSource),'f'))
            return 1
        else:
            return 0

    def viewMatrix( self, cutOffAngle=None, aspect=1.0, near=0.1, far=10000 ):
        """Calculate viewing matrix for our light

        Calculate our projection matrix, note that this assumes that
        we are a spot-like light with a narrow field-of-view
        (cutOffAngle).
        """
        if cutOffAngle is None:
            if hasattr( self, 'cutOffAngle' ):
                cutOffAngle = self.cutOffAngle /2 # note, in radians already...
            else:
                cutOffAngle = pi/3 # just a reasonable default
        return transformmatrix.perspectiveMatrix(
            cutOffAngle,
            aspect,
            near,
            far
        )
    def modelMatrix( self, direction=None ):
        """Calculate our model-side matrix"""
        if direction is None:
            direction = getattr( self,'direction',None)
        if direction:
            rot = vectorutilities.orientToXYZR( (0,0,-1), direction )
            # inverse of rotation matrix, hmm...
            rotate = transformmatrix.rotMatrix( rot )[1]
            # inverse of translation matrix...
            translate = transformmatrix.transMatrix(self.location)[1]
            return dot( translate,rotate )
        else:
            # inverse of translation matrix...
            return transformmatrix.transMatrix(self.location)[1]

class PointLight(basenodes.PointLight, Light):
    """PointLight node

    attributes:
        attenuation -- 3 values giving the light-attenuation
            values for constant, linear and quadratic attenuation
        (+ Light attributes)
    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointLight
    """
    def Light( self, lightID, mode = None):
        """Render the light (i.e. cause it to alter the scene"""
        if super(PointLight,self).Light( lightID, mode ):
            glLightf(lightID, GL_CONSTANT_ATTENUATION, self.attenuation[0])
            glLightf(lightID, GL_LINEAR_ATTENUATION, self.attenuation[1])
            glLightf(lightID, GL_QUADRATIC_ATTENUATION, self.attenuation[2])
            return 1
        else:
            return 0
    def modelMatrix( self, direction=None ):
        """Calculate our model-side matrix"""
        if direction is None and hasattr( self, 'direction' ):
            direction = self.direction
        rot = vectorutilities.orientToXYZR( (0,0,-1), direction )
        # inverse of rotation matrix, hmm...
        rotate = transformmatrix.rotMatrix( rot )[1]
        # inverse of translation matrix...
        translate = transformmatrix.transMatrix(self.location)[1]
        if rotate is not None and translate is not None:
            return dot( translate,rotate )
        elif rotate is not None:
            return rotate 
        elif translate is not None:
            return translate 
        else:
            return identity((4,4),type='f')

class SpotLight(basenodes.SpotLight, PointLight):
    """SpotLight node

    attributes:
        cutOffAngle -- spotlight falloff from the center-line
        (+ Light attributes)
    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#SpotLight
    """
    def Light( self, lightID, mode = None):
        """Render the light (i.e. cause it to alter the scene"""
        if super(SpotLight,self).Light( lightID, mode ):
            # now the spotlight-specific stuff
            glLightfv(lightID, GL_SPOT_DIRECTION, self.direction.astype( 'f'))
            glLightf(lightID, GL_SPOT_CUTOFF, self.cutOffAngle* (180/pi))
            # note no support for GL_SPOT_EXPONENT/beamWidth
            glLightf(lightID, GL_QUADRATIC_ATTENUATION, self.attenuation[2])
            return 1
        else:
            return 0


class DirectionalLight (basenodes.DirectionalLight, Light):
    '''A Directional Light node
    Note: this is not scoped according to vrml standard,
    instead it affects the entire scene

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#DirectionalLight
    '''
    pointSource = 0.0
