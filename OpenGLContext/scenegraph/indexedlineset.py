"""IndexedLineSet VRML97 node implemented using display-lists"""
from OpenGL.GL import *
from OpenGLContext import displaylist
from vrml import cache
from OpenGLContext.scenegraph import coordinatebounded
from OpenGLContext.scenegraph import vertex 
from vrml.vrml97 import basenodes
import warnings
from vrml import protofunctions

class IndexedLineSet(
    coordinatebounded.CoordinateBounded,
    basenodes.IndexedLineSet
):
    """VRML97-style Line-Set object

    The IndexedLineSet provides GL_LINE/GL_LINE_STRIP
    geometry, with support for per-vertex or whole-set
    colors.

    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/part1/nodesRef.html#IndexedLineSet
    
    # This code is not OpenGL 3.1 compatible
    """
    def compile( self, mode=None ):
        """Compile the IndexedLineSet into a display-list
        """
        if self.coord and len(self.coord.point) and len(self.coordIndex):
            dl = displaylist.DisplayList()
            holder = mode.cache.holder(self, dl)
            for field in protofunctions.getFields( self ):
                # change to any field requires a recompile
                holder.depend( self, field )
            for (n, attr) in [
                (self.coord, 'point'),
                (self.color, 'color'),
            ]:
                if n:
                    holder.depend( n, protofunctions.getField(n,attr) )
                
            points = self.coord.point
            indices = expandIndices( self.coordIndex )
            #XXX should do sanity checks here...
            if self.color and len(self.color.color):
                colors = self.color.color
                if self.colorPerVertex:
                    if len(self.colorIndex):
                        colorIndices = expandIndices( self.colorIndex )
                    else:
                        colorIndices = indices
                else:
                    if len(self.colorIndex):
                        # each item represents a single polyline colour
                        colorIndices = self.colorIndex
                    else:
                        # each item in color used in turn by each polyline
                        colorIndices = range(len(indices))
                # compile the color-friendly ILS
                dl.start()
                try:
                    glEnable( GL_COLOR_MATERIAL )
                    for index in range(len(indices)):
                        polyline = indices[index]
                        color = colorIndices[index]
                        try:
                            color = int(color)
                        except (TypeError,ValueError), err:
                            glBegin( GL_LINE_STRIP )
                            try:
                                for i,c in map(None, polyline, color):
                                    if c is not None:
                                        # numpy treats None as retrieve all??? why?
                                        currentColor = colors[c]
                                        if currentColor is not None:
                                            glColor3d( *currentColor )
                                    glVertex3f(*points[i])
                            finally:
                                glEnd()
                        else:
                            glColor3d( *colors[color] )
                            glBegin( GL_LINE_STRIP )
                            try:
                                for i in polyline:
                                    glVertex3f(*points[i])
                            finally:
                                glEnd()
                    glDisable( GL_COLOR_MATERIAL )
                finally:
                    dl.end()
            else:
                dl.start()
                try:
                    for index in range(len(indices)):
                        polyline = indices[index]
                        glBegin( GL_LINE_STRIP )
                        try:
                            for i in polyline:
                                glVertex3f(*points[i])
                        finally:
                            glEnd()
                finally:
                    dl.end()
            return dl
        return None

    def render (
        self,
        visible = 1, # can skip normals and textures if not
        lit = 1, # can skip normals if not
        textured = 1, # can skip textureCoordinates if not
        transparent = 0, # need to sort triangle geometry...
        mode = None, # the renderpass object for which we compile
    ):
        """Render the IndexedFaceSet's geometry for a Shape

            visible -- if false, do nothing
            lit - ignored
            textured -- ignored
            transparent -- ignored
        """
        if visible:
            dl = mode.cache.getData(self)
            if not dl:
                dl = self.compile(mode=mode)
            if dl is None:
                return 1
            # okay, is now a (cached) display list object
            dl()
        return 1

    def yeildVertices( self ):
        """Yield set of vertices to be rendered..."""
        # this is an unfinished start to getting OpenGL 3.1 operation
        if self.coord and len(self.coord.point) and len(self.coordIndex):
            points = self.coord.point
            indices = expandIndices( self.coordIndex )
            currentColor = None
            #XXX should do sanity checks here...
            if self.color and len(self.color.color):
                colors = self.color.color
                if self.colorPerVertex:
                    if len(self.colorIndex):
                        colorIndices = expandIndices( self.colorIndex )
                    else:
                        colorIndices = indices
                else:
                    if len(self.colorIndex):
                        # each item represents a single polyline colour
                        colorIndices = self.colorIndex
                    else:
                        # each item in color used in turn by each polyline
                        colorIndices = range(len(indices))
                # compile the color-friendly ILS
                for index in range(len(indices)):
                    polyline = indices[index]
                    color = colorIndices[index]
                    try:
                        color = int(color)
                    except (TypeError,ValueError), err:
                        for i,c in map(None, polyline, color):
                            if c is not None:
                                # numpy treats None as retrieve all??? why?
                                currentColor = colors[c]
                            yield currentColor, points[i]
                    else:
                        for i in polyline:
                            yield colors[color], points[i]
                        yield None
            else:
                for index in range(len(indices)):
                    polyline = indices[index]
                    for i in polyline:
                        yield None, points[i]
                    yield None

def expandIndices( indices ):
    """Create a set of poly-line definitions"""
    items = []
    current = []
    for i in indices:
        if i == -1:
            if len(current)<2:
                # should warn the user
                warnings.warn( """IndexedLineSet Polyline of length < 2""")
            else:
                items.append( current )
            current = []
        else:
            current.append( i )
    if current:
        items.append( current )
    return items