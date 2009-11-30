"""Shadow-volume implementation

A volume is cast by a light from an edgeset, it's
basically the volume of space which is shadowed by
the given edgeset/object.
"""
from OpenGLContext.arrays import *
from OpenGL.GL import *
import weakref

class Volume( object ):
    """A shadow-volume object

    This object represents the shadow cast by a single
    light and a single occluder of that light.  It is
    rendered (along with all other volumes for a given
    light) into the stencil buffer to determine what
    parts of the scene are lit by the light.

    XXX doesn't yet handle single-edges for faces or
    (more cricitally) clock-wise windings
    """
    forwardIndices = ()
    sideType = 0 # GL_TRIANGLES or GL_QUADS
    backFaces = ()
    edgeSet = None # weakref to edge-set
    light = None # weakref to light

    def __init__( self, edgeSet, sourceVector ):
        """Initialize the shadow volume

        edgeSet -- pointer to the edge set from which we
            retrieve most of our geometric data
        sourceVector -- the homogenous coordinates of the
            shadow-casting light.
        """
        self.edgeSet = weakref.proxy( edgeSet )
        self.sourceVector = sourceVector
        self.calculate()
    def calculate( self ):
        """Calculate the shadow-volume's shape

        Returns segments*2*3 array where each item in the array
        has the property that it defines a face of the shadow
        volume like so:
            A,B = segment (2 3-item arrays)
            for point lights (Quads):
                Ax,Ay,Az,1.0
                Bx,By,Bz,1.0
                Bx,By,Bz,0.0
                Ax,Ay,Az,0.0
            for directional lights:
                Ax,Ay,Az,1.0
                Bx,By,Bz,1.0
                0,0,0,0
        Which is fed into the "equation 14" or "equation 15"
        of the article.  Note that this is pre-calculated to not
        require switching calculations on the face when doing
        the later transformation to a shadow volume.  (i.e. in
        the article there are two different cases for
        whether the "first" or "second" face is facing the lights,
        I've folded them together).

        need certain things when we're done:
            set of light-facing-faces
            set of rearward-facing-faces (projected to infinity)
            set of edge-faces (silouhette projected to infinity)
        # the first two are currently missing
        # should do those as indices into the points array
        """
        #sourceVector is the light position, with the fourth-item
        #of the vector being 1.0 for point lights and 0.0
        #for directional lights
        sourceVector = self.sourceVector
        positional = sourceVector[-1]
        if positional:
            # is a positional light
            self.sideType = GL_QUADS
        else:
            self.sideType = GL_TRIANGLES
        edges1 = self.singleEdges( sourceVector )
        edges2 = self.doubleEdges( sourceVector )

        self.shadowCaps( sourceVector )

        # now compound the two sources together
        # these are all now edges to be turned into
        # faces for the sides of the shadow-volume
        edges1 = concatenate( (edges1, edges2) )

        # calculate the edge-faces here...
        if self.sideType == GL_QUADS:
            l = array( sourceVector[:3], 'd' )
            points = zeros( (len(edges1)*4,4), 'd' )
            points[1::4,:3] = edges1[:,1] # B
            points[0::4,:3] = edges1[:,0] # A
            # A.w and B.w are always one (in this code)
            # so we can simplify a few of the equations...
            points[3::4,:3] = (
                edges1[:,0] * positional # A*l.w
                -
                l # l*A.w == l* 1.0 == l
            )
            points[2::4,:3] = (
                edges1[:,1] * positional
                -
                l # B*l.w - l*B.w
            )
            points[0::4,3] = 1
            points[1::4,3] = 1
        else: # Triangles
            l = - array( sourceVector, 'd' )
            points = zeros( (len(edges1)*3,4), 'd' )
            points[0::3,:3] = edges1[:,1] # B
            points[1::3,:3] = edges1[:,0] # A
            points[2::3,:] = l # A*l.w - l*A.w
            points[0::3,3] = 1
            points[1::3,3] = 1
        self.edges = points
            
        
        
    def doubleEdges( self, sourceVector ):
        """Calculate double-face-edges for given sourceVector

        Returns an Nx2x3 array of line-segment coordinates
        """
        doubleEdges = self.edgeSet.doubleEdges
        doubleVectors = self.edgeSet.doubleVectors
        if not doubleEdges:
            return zeros( (0,2,3),'d')
        indices = arange(0,len(doubleVectors))
        ### Calculate the forward and backward-facing triangle-sets...
        mults = greater(
            dot(doubleVectors, sourceVector ),
            0
        )
        #indices -> only those which are edges
        # if one is and one isn't, then it's a silouhette edge
        indices = nonzero(
            equal(
                sum(
                    mults,
                    1 # second axis
                ),
                1 # everything that isn't 0 or 2 in this case
            )
        )[0] # just care about first dimension
        
        # vectors is now just those which are edges...
        vectors = take( doubleVectors, indices, 0 )
        edges = take( doubleEdges, indices, 0 )

        # mults gives a map which filters the doubleIndices value
        # mults is now just those edges which are part of the silouhette
        mults = take( mults, indices, 0 )
        # the set of silouhette vertices where the second face faces...
        vectors1 = compress( mults[:,1], edges,0 )
        # the set of vertices where the first face faces...
        vectors2 = compress( mults[:,0], edges,0 )
        # these need to have their coord-order swapped to allow
        # for uniform treatment...
        a = vectors2[:,1::2][:]
        b = vectors2[:,::2][:]
        vectors2 = zeros(shape(vectors2),'d')
        vectors2[:,1::2] = b
        vectors2[:,::2] = a
        # the vector-sets are now homogenous, so we concatenate and
        # return the result
        return concatenate((vectors2,vectors1))
        
    def singleEdges( self, sourceVector ):
        """Calculate single-face-edges for given sourceVector

        Returns an Nx2x3 array of line-segment coordinates
        """
        # if the face is facing, then is an edge, otherwise not
        singleEdges = self.edgeSet.singleEdges
        singleVectors = self.edgeSet.singleVectors
        if not singleVectors:
            return zeros( (0,2,3),'d')
        indices = nonzero(
            greater(
                dot(singleVectors, sourceVector ),
                0
            )
        )
        return take(
            singleEdges,
            indices,
            0
        )
        
    def shadowCaps( self, sourceVector):
        """Calculate the shadow-volume caps

        Forward cap is just indices into the points array
        Backward cap requires a new points array
        """
        ### Calculate the forward/backward face-sets
        directions = dot(self.edgeSet.planeEquations, sourceVector)
        def expand( forwardIndices ):
            """Expand a set into point-indices from tri-indices"""
            forwardIndices = repeat(forwardIndices,3,0)
            forwardIndices[1::3] +=1
            forwardIndices[2::3] +=2
            return forwardIndices
        self.forwardIndices = expand(nonzero(greater(directions,0))[0])

        # backward is trickier, as we need to project to infinity
        # from the light position
        if sourceVector[-1]:
            backwardIndices = expand(nonzero(less_equal(directions,0))[0])
            ### Now need to project backward with this equation:
            ## Vertex4f(V.x*L.w-L.x*V.w, V.y*L.w-L.y*V.w,V.z*L.w-L.z*V.w, 0);
            ## where V is the given vertex and L is our sourceVector
            ## and the source V.w is 1.0 (model-space)
            ## V.x *L.w - L.x, 
            L = array(sourceVector,'d')
            V = take( self.edgeSet.points, backwardIndices,0 )
            set = zeros((len(V),4),'d')
            
            set[:,0:3] = (V[:,0:3]*L[-1])-L[0:3]
            self.backwardPoints = set
        
    def render( self, mode=None ):
        """Render the shadow-volume
        """
        if mode.stencil:
            # XXX these shouldn't be here, but we're making sure
            # the state really is what we want during testing
            if not self.edgeSet.ccw:
                glFrontFace( GL_CW )
            try:
                if __debug__:
                    if mode.debugShadowNoStencil:
                        glStencilMask( 0 )

                if not mode.debugShadowNoFrontFaces:
                    # now render front-facing polygons
                    glStencilOp(GL_KEEP, GL_KEEP, GL_INCR);

                    glCullFace(GL_BACK);
                    if __debug__:
                        if mode.debugShadowVolume:
                            glColorMask(0,1,0,0)
                    ## as far as I can see, there is no way for either
                    ## the cap or the boot to change anything on this pass,
                    ## so why bother rendering them?
                    if not mode.debugShadowNoCaps:
                        self._render_cap()
                    if not mode.debugShadowNoEdges:
                        self._render_edges()
                    if not mode.debugShadowNoBoots:
                        self._render_boot()
                    if mode.debugShadowSilouhette:
                        glColorMask(0,1,1,0)
                        self._debug_render_silouhette()
                if __debug__:
                    glColorMask(0,0,0,0)

                if not mode.debugShadowNoBackFaces:
                    glStencilOp(GL_KEEP,GL_KEEP,GL_DECR);

                    glCullFace(GL_FRONT);
                    if __debug__:
                        if mode.debugShadowVolume:
                            glColorMask(1,0,0,0)
                    if not mode.debugShadowNoCaps:
                        self._render_cap()
                    if not mode.debugShadowNoEdges:
                        self._render_edges()
                    if not mode.debugShadowNoBoots:
                        self._render_boot()
            finally:
                glFrontFace( GL_CCW )
                if __debug__:
                    glColorMask(0,0,0,0);
                    glStencilMask( ~0 )
    def _render_cap( self ):
        """Render the shadow-volume cap (forward-facing faces)"""
        if self.forwardIndices is not None:
            glVertexPointerd( self.edgeSet.points )
            glEnableClientState(GL_VERTEX_ARRAY);
            glDrawElementsui(
                GL_TRIANGLES,
                self.forwardIndices,
            )
            glDisableClientState(GL_VERTEX_ARRAY);
    def _render_boot( self ):
        """Render the shadow-volume boot (backward-facing faces projected)"""
        if self.sideType != GL_TRIANGLES and self.backwardPoints is not None:
            # if triangles, the volume converges to a point, so there
            # can be no back-facing polygons...
            glVertexPointerd(self.backwardPoints )
            glEnableClientState(GL_VERTEX_ARRAY);
            glDrawArrays(GL_TRIANGLES, 0, len(self.backwardPoints))
            glDisableClientState(GL_VERTEX_ARRAY);
        
    def _render_edges( self ):
        """Render the shadow-volume edges"""
        # ignore mode while building...
        if self.edges is not None:
            glEnableClientState(GL_VERTEX_ARRAY);
            glVertexPointerd(self.edges )
            assert self.sideType != 0, """%s _render_edges called before sideType determined"""%( self.__class__ )
            glDrawArrays( self.sideType, 0, len(self.edges))
            glDisableClientState(GL_VERTEX_ARRAY);
    def _debug_render_silouhette( self ):
        """Debug render of silouhette as lines with current colour"""
        ### debug-rendering-mode
        ##  draws edges as blue lines...
        from OpenGL.GLUT import glutWireSphere
        if self.sideType == GL_TRIANGLES:
            step = 3
        else:
            step = 4
        Bs = self.edges[0::step]
        As = self.edges[1::step]
        glBegin( GL_LINES )
        for A,B in map(None, As, Bs):
            glColor3f( 0,0,1.0)
            glVertex4dv( A )
            glColor3f( 0,1.0,.5)
            glVertex4dv( B )
        glEnd( )

        glPushMatrix()
        glTranslate( *self.sourceVector[:3])
        glutWireSphere( .2,8,8)
        glPopMatrix()
        