#! /usr/bin/env python
"""=RedBook NURBS Trim=

[nurbsobject.py-screen-0001.png Screenshot]

This tutorial demonstrates more involve usage of the OpenGLContext
scenegraph NURBs nodes.  It implements the RedBook trimmed-nurbs
demo using the scenegraph API.

This version includes an animation that morphs the NURBS surface
through different shapes: original mound, flattened, expanded, and risen.
"""

from __future__ import print_function
from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGLContext.arrays import *

from OpenGLContext.scenegraph.basenodes import *
from OpenGLContext.scenegraph.interpolators import SetInterpolator
from vrml.vrml97 import basenodes
from vrml import field


class ArrayCoordinateInterpolator(SetInterpolator, basenodes.CoordinateInterpolator):
    """CoordinateInterpolator that reshapes output to a specified array shape.

    This subclass extends CoordinateInterpolator to support reshaping the
    interpolated coordinate arrays into multi-dimensional arrays suitable
    for NURBS control points.

    Fields:
        outputShape: tuple specifying the final shape of the output array
                    (e.g., (4, 4, 3) for a 4x4 grid of 3D control points)
    """
    PROTO = 'ArrayCoordinateInterpolator'
    outputShape = field.newField('outputShape', 'SFVec3f', 1, [4, 4, 3])

    def on_set_fraction(self, value):
        """Override to reshape the interpolated value to outputShape."""
        super(ArrayCoordinateInterpolator, self).on_set_fraction(value)
        if hasattr(self, 'value_changed') and self.value_changed is not None:
            # Reshape the flat array to the desired output shape
            shape = tuple(int(x) for x in self.outputShape)
            self.value_changed = reshape(self.value_changed, shape)


class TestContext(BaseContext):
    """RedBook Trimmed Nurbs Demo"""

    """Setup a reasonably close camera."""
    initialPosition = (0, 0, 3)

    def buildControlPoints(self, centerHeight=3.0, edgeHeight=-3.0):
        """Build control points for the main surface.

        We create a single 4x4x3 grid that holds the control
        points for the main surface. The center 2x2 points are
        raised to centerHeight, while edges are at edgeHeight.

        Args:
            centerHeight: Z value for center control points (default 3.0)
            edgeHeight: Z value for edge control points (default -3.0)
        """
        ctlpoints = zeros((4, 4, 3), "d")
        for u in range(4):
            for v in range(4):
                ctlpoints[u][v][0] = 2.0 * (u - 1.5)
                ctlpoints[u][v][1] = 2.0 * (v - 1.5)
                if (u == 1 or u == 2) and (v == 1 or v == 2):
                    ctlpoints[u][v][2] = centerHeight
                else:
                    ctlpoints[u][v][2] = edgeHeight
        return ctlpoints

    def buildAnimationKeyframes(self):
        """Build the four keyframe control point arrays for morphing animation.

        Creates subtle variations to show dynamism in the curved surface:
        - Original: standard mound shape
        - Softened: slightly reduced center height
        - Warped: outer corners shifted to tilt the surface
        - Raised: slightly taller peak
        Then back to original.
        """
        original = self.buildControlPoints(centerHeight=3.0, edgeHeight=-3.0)

        # Softened: reduce center height by half the difference
        softened = self.buildControlPoints(centerHeight=1.5, edgeHeight=-3.0)

        # Warped: shift outer corner points to create a tilted/twisted effect
        warped = self.buildControlPoints(centerHeight=3.0, edgeHeight=-3.0)
        # Raise two opposite corners, lower the other two
        warped[0, 0, 2] += 1.5   # corner (0,0) up
        warped[3, 3, 2] += 1.5   # corner (3,3) up
        warped[0, 3, 2] -= 1.0   # corner (0,3) down
        warped[3, 0, 2] -= 1.0   # corner (3,0) down

        # Raised: slightly taller peak with edges pulled in
        raised = self.buildControlPoints(centerHeight=4.0, edgeHeight=-2.5)

        # Flatten each to 1D for the interpolator keyValue array
        # Keys: 0.0=original, 0.25=softened, 0.5=warped, 0.75=raised, 1.0=original
        keyValue = concatenate([
            original.flatten(),
            softened.flatten(),
            warped.flatten(),
            raised.flatten(),
            original.flatten(),  # Loop back to start
        ])
        return keyValue

    def OnInit(self):
        """Create the scenegraph"""
        print("""You should see a multi-coloured Nurbs surface
with an ice-cream-cone-shaped trimming curve
(a hole cut out of it).""")

        """GLU Nurbs trims via contours which are applied in the 
        same way as tessellation, i.e. your outermost contour will 
        trim off the edges of your nurbs, while inner contours will 
        cut "holes" in to the Nurbs.  Since we don't want to trim off 
        the edge of the hill, we define a contour that includes all 
        of the surface.  The coordinates are in the parametric 
        coordinate system, so 0.0 is the start and 1.0 is the finish.
        """
        trimmingContour = [
            Contour2D(
                children=[
                    Polyline2D(
                        # outside edge
                        point=array(
                            [
                                [0.0, 0.0],
                                [1.0, 0.0],
                                [1.0, 1.0],
                                [0.0, 1.0],
                                [0.0, 0.0],
                            ],
                            "d",
                        )
                    ),
                ],
            ),
            Contour2D(
                children=[
                    Polyline2D(
                        # inside edge
                        point=array(
                            [
                                [0.75, 0.5],
                                [0.5, 0.25],
                                [0.25, 0.5],
                            ],
                            "d",
                        )
                    ),
                    NurbsCurve2D(
                        knot=array([0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0], "d"),
                        controlPoint=array(
                            [
                                [0.25, 0.5],
                                [0.25, 0.75],
                                [0.75, 0.75],
                                [0.75, 0.5],
                            ],
                            "d",
                        ),
                    ),
                ]
            ),
        ]

        knots = [0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0, 1.0]
        """The color array is indexed to the control-point array 
        when/if it is provided.  Here we make a progression of colours 
        across the surface"""
        color = zeros((4, 4, 3), "d")
        color[0, :, :] = (1.0, 0, 0)
        color[1, :, :] = (0.66, 0.33, 0)
        color[2, :, :] = (0.33, 0.66, 0)
        color[3, :, :] = (0, 1.0, 0)
        self.shape = Shape(
            appearance=Appearance(
                material=Material(),
            ),
            geometry=TrimmedSurface(
                surface=NurbsSurface(
                    controlPoint=self.buildControlPoints(),
                    color=color,
                    vDimension=4,
                    uDimension=4,
                    uKnot=knots,
                    vKnot=knots,
                    sampling=NurbsToleranceSample(tolerance=3.0),
                ),
                trimmingContour=trimmingContour,
            ),
        )
        # Create the morphing animation components
        animationNodes = [
            ArrayCoordinateInterpolator(
                DEF='Surface-Morph',
                key=[0.0, 0.25, 0.5, 0.75, 1.0],
                keyValue=self.buildAnimationKeyframes(),
                outputShape=(4, 4, 3),
            ),
            TimeSensor(
                DEF='Morph-Timer',
                cycleInterval=8.0,  # 8 seconds per full cycle
                loop=True,
            ),
        ]

        self.sg = sceneGraph(
            children=[
                Transform(
                    scale=[0.5, 0.5, 0.5],
                    rotation=[1, 0, 0, -0.5],
                    children=[self.shape],
                ),
            ] + animationNodes,
        )

        # Route timer fraction to interpolator
        self.sg.addRoute(
            'Morph-Timer', 'fraction_changed',
            'Surface-Morph', 'set_fraction'
        )
        # Route interpolated values to our handler that updates the surface
        self.sg.addRoute(
            'Surface-Morph', 'value_changed',
            self.onMorphUpdate
        )

    def onMorphUpdate(self, value):
        """Handle morphed control point values from the interpolator."""
        # Update the NURBS surface control points with the interpolated values
        self.shape.geometry.surface.controlPoint = value


if __name__ == "__main__":
    TestContext.ContextMainLoop()
