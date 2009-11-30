"""VPython-style curve object, similar to an IndexedLineSet"""
from OpenGL.GL import *
from OpenGLContext import displaylist
from vrml import cache
from vrml.vrml97 import nodetypes
from vrml import node, field, protofunctions
from OpenGLContext.arrays import concatenate, asarray

class VPCurve( nodetypes.Rendering, nodetypes.Children, node.Node ):
    """VPython-style curve object, similar to an IndexedLineSet"""
    color = field.newField( 'color', 'MFColor', 1, [(1,1,1),])
    pos = field.newField( 'pos', 'MFVec3f', 1, list)
    radius = field.newField( 'radius', 'SFFloat', 1, 0.0)
    def append( self, pos=None, color=None, **arguments ):
        """Append a single point to the curve"""
        def merge( main, partials, default ):
            if main is not None:
                return main
            result = []
            for a,b in zip(partials, default):
                if a is None:
                    result.append( b )
                else:
                    result.append( a )
            return result
        if len(self.color):
            last = self.color[-1]
        else:
            last = (1,1,1)
        color = merge(
            color,
            [arguments.get(n) for n in ('red','green','blue')],
            last
        )
        if len( self.pos ):
            last = self.pos[-1]
        else:
            last = (0,0,0)
        pos = merge(
            pos,
            [arguments.get(n) for n in ('x','y','z')],
            last
        )
        positions = self.pos
        colors = self.color
        positions = concatenate( (positions, (pos,)))
        colors = concatenate( (colors, (color,)))
        self.color = colors
        self.pos = positions
    def Render (self, mode = None):
        """Do run-time rendering of the Shape for the given mode"""
        if mode.visible:
            dl = mode.cache.getData(self)
            if not dl:
                dl = self.compile(mode=mode)
            if dl is None:
                return None
            # okay, is now a (cached) display list object
            dl()
        return None
    def compile( self, mode=None ):
        """Compile the VPCurve into a display-list
        """
        # This code is not OpenGL 3.1 compatible
        if self.pos.any():
            dl = displaylist.DisplayList()
            #XXX should do sanity checks here...
            dl.start()
            try:
                pos = self.pos
                color = self.color
                colorLen = len(color)
                killThickness = 0
                if self.radius:
                    glLineWidth( self.radius*2 )
                    killThickness = 1
                try:
                    
                    glEnable( GL_COLOR_MATERIAL )
                    try:
                        glBegin( GL_LINE_STRIP )
                        try:
                            lastColor = None
                            for index in range(len(pos)):
                                point = pos[index]
                                if index < colorLen:
                                    col = tuple(color[index])
                                    if  col != lastColor:
                                        glColor3dv( col )
                                    lastColor = col
                                glVertex3dv(point)
                        finally:
                            glEnd()
                    finally:
                        glDisable( GL_COLOR_MATERIAL )
                finally:
                    if killThickness:
                        glLineWidth( 1 )
            finally:
                dl.end()
            holder = mode.cache.holder(self, dl)
            for field in protofunctions.getFields( self ):
                # change to any field requires a recompile
                holder.depend( self, field )
            return dl
        return None
    