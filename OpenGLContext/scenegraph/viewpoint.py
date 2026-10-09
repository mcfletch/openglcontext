"""X3D's and VRML97's Viewpoint, and X3D's OrthoViewpoint"""
import math
from typing import Any, Optional

from vrml.vrml97 import basenodes
from vrml.x3d import nodes as x3d
from OpenGLContext import quaternion
from OpenGLContext import arrays


class Placing:
    """A viewpoint that places a context's view platform when it is bound

    Its position and orientation (:meth:`placement`) where `jump` is true,
    its projection (:meth:`project`), and the clip planes `nearDistance` and
    `farDistance` where each is positive.
    """

    nearDistance: Any
    farDistance: Any
    fieldOfView: Any
    position: Any
    orientation: Any
    centerOfRotation: Any

    def placement( self ) -> "tuple[Any, quaternion.Quaternion]":
        """(position, orientation) in the viewpoint's own coordinates"""
        return self.position, quaternion.fromXYZR( *self.orientation )

    def localCentre( self ) -> Any:
        """`centerOfRotation` in the viewpoint's own coordinates"""
        return self.centerOfRotation

    def speedScale( self, position: Any ) -> float:
        """What navigation speeds are multiplied by with the viewer at `position`"""
        return 1.0

    def moveTo( cls, path: Any, context: Any ) -> None:
        """Given a node-path to a viewpoint, move context's platform there"""
        matrix = path.transformMatrix( )
        node = path[-1]
        platform = context.platform
        if not platform:
            platform = context.platform = context.getViewPlatform()
        if node.jump:
            local, turned = node.placement()
            position = list(local)+[1]
            newPosition = arrays.dot( position, matrix )
            newOrientation = ( path.quaternion() * turned ).XYZR()
            platform.setOrientation( newOrientation )
            if getattr( node, 'viewAll', False ):
                framed = node.framing( context, platform )
                if framed is not None:
                    newPosition = framed
            platform.setPosition( newPosition )
        node.project( platform )

    def framing( self, context: Any, platform: Any ) -> Optional[Any]:
        """Where the camera sees the whole scene, looking the way `platform` faces; None without bounds

        Back from the scene's centre along the view by the distance at which
        its bounding sphere fills the field of view.
        """
        bounds = getattr( context, 'sceneBounds', lambda: None )()
        if bounds is None:
            return None
        centre, radius = bounds
        half = self.halfView()
        distance = float( radius ) / max( math.sin( half ), 1e-6 )
        forward = platform.quaternion * [0.0, 0.0, -1.0, 0.0]
        return arrays.array( centre[:3], 'd' ) - arrays.array( forward[:3], 'd' ) * distance

    def halfView( self ) -> float:
        """Half the field of view the scene is framed in, radians"""
        return float( self.fieldOfView ) / 2.0

    def clipping( self ) -> "tuple[Optional[float], Optional[float]]":
        """(near, far): the clip distances, None for each the platform keeps

        `nearDistance` and `farDistance` where positive; otherwise the
        `near` and `far` a loader (glTF) may set on the node.
        """
        near = float( self.nearDistance ) if self.nearDistance > 0 else getattr( self, 'near', None )
        far = float( self.farDistance ) if self.farDistance > 0 else getattr( self, 'far', None )
        return near, far

    def project( self, platform: Any ) -> None:
        """Give `platform` this viewpoint's projection"""
        raise NotImplementedError


class Perspective(Placing):
    """A viewpoint with a perspective projection, `fieldOfView` radians across"""

    def project( self, platform: Any ) -> None:
        """Give `platform` this viewpoint's perspective: `fieldOfView` radians
        across the view's smaller dimension"""
        platform.setFrustum( self.fieldOfView, None, *self.clipping(), across='smaller' )


class Viewpoint(Perspective, basenodes.Viewpoint):
    """VRML97's and X3D's Viewpoint: a perspective view

    Reference:
        http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#Viewpoint
    """


class OrthoViewpoint(Placing, x3d.OrthoViewpoint):
    """X3D's OrthoViewpoint: a view through an orthographic window

    `fieldOfView` is the window, (minimum x, minimum y, maximum x, maximum
    y) in the viewpoint's coordinates, widened along one axis to the shape
    of the view; one with fewer than four values is X3D's default window.
    """

    PROTO = 'OrthoViewpoint'

    #: The window X3D gives an OrthoViewpoint whose fieldOfView is too short.
    DEFAULT_WINDOW = (-1.0, -1.0, 1.0, 1.0)

    def halfView( self ) -> float:
        """A right angle's half: the scene is framed as a perspective view of it would be"""
        return math.pi / 4.0

    def project( self, platform: Any ) -> None:
        """Give `platform` this viewpoint's orthographic window"""
        window = [float( value ) for value in self.fieldOfView]
        platform.setOrthographic(
            window[:4] if len( window ) >= 4 else self.DEFAULT_WINDOW,
            *self.clipping()
        )
