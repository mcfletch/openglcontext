"""Standard Light-node types"""
from typing import TYPE_CHECKING, Any

from OpenGL.GL import *
from math import pi, sqrt
from vrml.vrml97 import basenodes, nodetypes
from vrml.vrml97 import transformmatrix
from vrml import node, field
from OpenGLContext.arrays import array, dot, identity
from OpenGLContext import vectorutilities
from OpenGLContext.passes.shadowmath import SHADOW_DEPTH_BIAS

if TYPE_CHECKING:
    class _LightHost:
        """The VRML97 light fields ``Light`` reads of the node beside it.

        Each concrete light is that node and this mix-in together --
        ``class PointLight(basenodes.PointLight, Light)`` -- so the fields
        resolve along the MRO at run time.  Aliased to ``object`` there, so the
        MRO is as it was.

        ``location`` and ``direction`` are the exception to "every light has
        these": a PointLight has a location and no direction, a
        DirectionalLight the reverse, a SpotLight both.  That is why the code
        asks with ``hasattr`` and ``getattr`` rather than reading them
        outright.
        """
        on: bool
        color: Any
        intensity: float
        ambientIntensity: float
        location: Any
        direction: Any
else:
    _LightHost = object


#: The widest field of view, in radians, a light's perspective is drawn with.
SPOT_PERSPECTIVE_LIMIT = 2 * pi / 3


class Light(_LightHost):#nodetypes.Light, nodetypes.Children, node.Node ):
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
    def Light( self, lightID: int, mode: Any = None ) -> int:
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

    def viewMatrix(
        self, cutOffAngle: float | None = None, aspect: float = 1.0,
        near: float = 0.1, far: float = 10000, inverse: bool = False,
    ) -> Any:
        """Calculate viewing matrix for our light

        A perspective over the light's cone: the full field of view, twice
        the spot's ``cutOffAngle``, capped at ``SPOT_PERSPECTIVE_LIMIT``. A
        wider cone (X3D's default is a half-angle of pi/2) is drawn to that
        limit. ``cutOffAngle`` here is the full field of view, in radians.
        """
        if cutOffAngle is None:
            if hasattr( self, 'cutOffAngle' ):
                cutOffAngle = self.cutOffAngle * 2 # radians
            else:
                cutOffAngle = pi/3 # just a reasonable default
        return transformmatrix.perspectiveMatrix(
            min(cutOffAngle, SPOT_PERSPECTIVE_LIMIT),
            aspect,
            near,
            far,
            inverse=inverse,
        )
    def modelMatrix( self, direction: Any = None, inverse: bool = False ) -> Any:
        """World coordinates into this light's own frame

        Carries ``location`` to the origin and ``direction`` onto -Z, which
        is the transform a shadow pass renders the depth map through.
        ``inverse=True`` gives the other direction, the light's placement in
        the world.  ``direction`` overrides the field for a caller that is
        already tracking one, as the shadow tutorial does for its animated
        light.

        Which fields exist depends on the light: a ``DirectionalLight`` has a
        direction and no location, a ``PointLight`` the reverse, a
        ``SpotLight`` both.  ``rotMatrix`` and ``transMatrix`` answer ``None``
        for a null rotation and a null translation, so a light at the origin
        shining down -Z has nothing to compose and gets the identity.
        """
        if direction is None:
            direction = getattr( self,'direction',None)
        # rotMatrix/transMatrix each return (forward, inverse); the
        # world-to-light matrix is built from the inverse halves.
        which = bool( not inverse )
        rotate = translate = None
        if direction is not None and len( direction ):
            rot = vectorutilities.orientToXYZR( (0,0,-1), direction )
            rotate = transformmatrix.rotMatrix( rot )[which]
        location = getattr( self, 'location', None )
        if location is not None:
            translate = transformmatrix.transMatrix( location )[which]
        if rotate is None:
            if translate is None:
                return identity( 4, dtype='f' )
            return translate
        if translate is None:
            return rotate
        if inverse:
            return dot( rotate,translate )
        return dot( translate,rotate )

class PointLight(basenodes.PointLight, Light):
    """PointLight node

    attributes:
        attenuation -- 3 values giving the light-attenuation
            values for constant, linear and quadratic attenuation
        (+ Light attributes)
    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#PointLight
    """
    #: X3D's `shadows`, true for a light made in code: a light casts shadows
    #: unless told not to. A light an X3D document builds has X3D's false
    #: unless the document says otherwise.
    shadows = field.newField('shadows', 'SFBool', 1, True)
    #: Another name for `shadows`, which engine code uses
    castShadows = field.AliasField('castShadows', 'shadows')
    #: How far the light reaches, in its own coordinates; nothing past it is
    #: lit. Unbounded for a light made in code; a light a VRML97 or X3D
    #: document builds has their 100 unless the document says otherwise.
    radius = field.newField('radius', 'SFFloat', 1, float('inf'))
    # Shadow-mapping controls (OpenGLContext extension fields)
    shadowBias = field.newField('shadowBias', 'SFFloat', 1, SHADOW_DEPTH_BIAS)
    shadowMapResolution = field.newField('shadowMapResolution', 'SFInt32', 1, 2048)

    def effectiveRange(self, threshold: float = 1.0 / 255.0) -> float | None:
        """Distance past which this light's contribution is negligible.

        Solves the VRML97 attenuation 1/(c + l*d + q*d^2) scaled by intensity
        for the distance where it drops below ``threshold``. Returns a positive
        radius, or None when the light never attenuates below the threshold
        (e.g. constant-only attenuation), meaning unbounded range.
        """
        c, l, q = (float(self.attenuation[0]), float(self.attenuation[1]),
                   float(self.attenuation[2]))
        intensity = max(float(self.intensity), 1e-6)
        # want intensity / (c + l*d + q*d^2) = threshold
        target = intensity / threshold  # = c + l*d + q*d^2
        if q > 1e-9:
            disc = l * l - 4 * q * (c - target)
            if disc < 0:
                return None
            return max(0.0, (-l + sqrt(disc)) / (2 * q))
        if l > 1e-9:
            return max(0.0, (target - c) / l)
        return None  # constant attenuation only -> unbounded

    def Light( self, lightID: int, mode: Any = None) -> int:
        """Render the light (i.e. cause it to alter the scene"""
        if super(PointLight,self).Light( lightID, mode ):
            glLightf(lightID, GL_CONSTANT_ATTENUATION, self.attenuation[0])
            glLightf(lightID, GL_LINEAR_ATTENUATION, self.attenuation[1])
            glLightf(lightID, GL_QUADRATIC_ATTENUATION, self.attenuation[2])
            return 1
        else:
            return 0

class SpotLight(basenodes.SpotLight, PointLight):
    """SpotLight node

    attributes:
        cutOffAngle -- spotlight falloff from the center-line
        (+ Light attributes)
    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#SpotLight
    """
    #: As :attr:`PointLight.radius`.
    radius = field.newField('radius', 'SFFloat', 1, float('inf'))

    def Light( self, lightID: int, mode: Any = None) -> int:
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

    With `global` true it lights the whole scene; with it false, only the
    descendants of its parent grouping node (:mod:`OpenGLContext.passes.lightscope`).
    True for one made in code, false for one a VRML97 world or an X3D
    document builds unless the document says otherwise. The fixed-function
    pipeline lights the whole scene either way.

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#DirectionalLight
    '''
    pointSource = 0.0
    #: X3D's `shadows`, true for a light made in code: a light casts shadows
    #: unless told not to. A light an X3D document builds has X3D's false
    #: unless the document says otherwise.
    shadows = field.newField('shadows', 'SFBool', 1, True)
    #: Another name for `shadows`, which engine code uses
    castShadows = field.AliasField('castShadows', 'shadows')
    # Shadow-mapping controls (OpenGLContext extension fields)
    shadowBias = field.newField('shadowBias', 'SFFloat', 1, SHADOW_DEPTH_BIAS)
    shadowMapResolution = field.newField('shadowMapResolution', 'SFInt32', 1, 2048)

    def effectiveRange(self, threshold: float = 1.0 / 255.0) -> float | None:
        """Directional lights have no attenuation; range is unbounded."""
        return None

# X3D's `global`, true for a DirectionalLight made in code: it lights the whole
# scene. One an X3D document or a VRML97 world builds lights only its siblings'
# subtrees unless the document says otherwise (passes.lightscope). 'global' is
# a Python keyword, so the field is set on the class.
setattr(DirectionalLight, 'global', field.newField('global', 'SFBool', 1, True))
