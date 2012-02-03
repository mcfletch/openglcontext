"""View frustum modeling as series of clipping planes

The Frustum object itself is only responsible for
extracting the clipping planes from an OpenGL model-view
matrix.  The bulk of the frustum-culling algorithm is
implemented in the bounding volume objects found in the
OpenGLContext.scenegraph.boundingvolume module.

Based on code from:
    http://www.markmorley.com/opengl/frustumculling.html
"""
from vrml import fieldtypes, node, protofunctions
from OpenGLContext.arrays import *
from OpenGL.GL import *
import logging 
log = logging.getLogger( __name__ )

def viewingMatrix(projection = None,model = None):
    """Calculate the total viewing matrix from given data

    projection -- the projection matrix, if not provided
        than the result of glGetDoublev( GL_PROJECTION_MATRIX)
        will be used.
    model -- the model-view matrix, if not provided
        than the result of glGetDoublev( GL_MODELVIEW_MATRIX )
        will be used.

    Note:
        Unless there is a valid projection and model-view
        matrix, the function will raise a RuntimeError
    """
    if projection is None:
        projection = glGetFloatv( GL_PROJECTION_MATRIX)
    if model is None:
        model = glGetFloatv( GL_MODELVIEW_MATRIX )
    # hmm, this will likely fail on 64-bit platforms :(
    if projection is None or model is None:
        log.warn( 
            """A NULL matrix was returned from glGetDoublev: proj=%s modelView=%s""",
            projection, model,
        )
        if projection:
            return projection
        if model:
            return model
        else:
            return identity( 4, 'd')
    return dot( model, projection )


class Frustum (node.Node):
    """Holder for frustum specification for intersection tests

    Note:
        the Frustum can include an arbitrary number of
        clipping planes, though the most common usage
        is to define 6 clipping planes from the OpenGL
        model-view matrices.
    """
    ARRAY_TYPE = 'f'
    planes = fieldtypes.MFVec4f( 'planes', 1, [])
    normalized = fieldtypes.SFBool( 'normalized', 0, 1)
    def fromViewingMatrix(cls, matrix= None, normalize=1):
        """Extract and calculate frustum clipping planes from OpenGL

        The default initializer allows you to create
        Frustum objects with arbitrary clipping planes,
        while this alternate initializer provides
        automatic clipping-plane extraction from the
        model-view matrix.

        matrix -- the combined model-view matrix
        normalize -- whether to normalize the plane equations
            to allow for sphere bounding-volumes and use of
            distance equations for LOD-style operations.
        """
        if matrix is None:
            matrix = viewingMatrix( )
        clip = ravel(matrix)
        frustum = zeros( (6, 4), cls.ARRAY_TYPE )
        # right
        frustum[0][0] = clip[ 3] - clip[ 0]
        frustum[0][1] = clip[ 7] - clip[ 4]
        frustum[0][2] = clip[11] - clip[ 8]
        frustum[0][3] = clip[15] - clip[12]
        # left
        frustum[1][0] = clip[ 3] + clip[ 0]
        frustum[1][1] = clip[ 7] + clip[ 4]
        frustum[1][2] = clip[11] + clip[ 8]
        frustum[1][3] = clip[15] + clip[12]
        # bottom
        frustum[2][0] = clip[ 3] + clip[ 1]
        frustum[2][1] = clip[ 7] + clip[ 5]
        frustum[2][2] = clip[11] + clip[ 9]
        frustum[2][3] = clip[15] + clip[13]
        # top
        frustum[3][0] = clip[ 3] - clip[ 1]
        frustum[3][1] = clip[ 7] - clip[ 5]
        frustum[3][2] = clip[11] - clip[ 9]
        frustum[3][3] = clip[15] - clip[13]
        # far
        frustum[4][0] = clip[ 3] - clip[ 2]
        frustum[4][1] = clip[ 7] - clip[ 6]
        frustum[4][2] = clip[11] - clip[10]
        frustum[4][3] = clip[15] - clip[14]
        # near
        frustum[5][0] = clip[ 3] + clip[ 2]
        frustum[5][1] = clip[ 7] + clip[ 6]
        frustum[5][2] = clip[11] + clip[10]
        frustum[5][3] = clip[15] + clip[14]
        if normalize:
            frustum = cls.normalize( frustum )
        return cls( planes = frustum, normalized = normalize )
    fromViewingMatrix = classmethod(fromViewingMatrix)
    def normalize(cls, frustum):
        """Normalize clipping plane equations"""
        magnitude = sqrt( 
            frustum[:,0] * frustum[:,0] + 
            frustum[:,1] * frustum[:,1] + 
            frustum[:,2] * frustum[:,2] 
        )
        # eliminate any planes which have 0-length vectors,
        # those planes can't be used for excluding anything anyway...
        frustum = compress( magnitude,frustum,0 )
        magnitude = compress( magnitude, magnitude,0 )
        magnitude=reshape(magnitude.astype(cls.ARRAY_TYPE), (len(frustum),1))
        return frustum/magnitude
    normalize = classmethod(normalize)
