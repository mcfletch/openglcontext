"""Gear node for use in geometry attribute of Shapes"""
from vrml import cache
from OpenGLContext.arrays import *
from OpenGL.arrays import vbo
from OpenGL.GL import *
from OpenGL.GLUT import glutSolidTeapot, glutWireTeapot
from vrml.vrml97 import nodetypes
from vrml import node, field, fieldtypes
from OpenGLContext import displaylist

class Gear( nodetypes.Geometry, node.Node ):
    """Simple Gear geometry (from gears.py)
    
    
    """
    PROTO = 'Gear'
    inner_radius = field.newField( 'inner_radius','SFFloat',1,.1 )
    outer_radius = field.newField( 'outer_radius','SFFloat',1,.5 )
    width = field.newField( 'width','SFFloat',1,.1 )
    teeth = field.newField( 'teeth','SFInt32',1,40 )
    tooth_depth = field.newField( 'tooth_depth', 'SFFloat', 1, .1 )
    
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # XXX should sort triangle geometry...
            mode = None, # the renderpass object for which we compile
        ):
        """Render the Teapot"""
        quick = mode.cache.getData(self)
        if not quick:
            quick = self.compile( mode=mode )
        if quick():
            quick()

    def boundingVolume( self, mode ):
        """Create a bounding-volume object for this node"""
        from OpenGLContext.scenegraph import boundingvolume
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current
        return boundingvolume.cacheVolume(
            self,
            boundingvolume.AABoundingBox(
                # This vastly overestimates the size!
                size = [self.outer_radius*2,self.outer_radius*2,self.width],
            ),
            ( 
                (self, 'outer_radius'), 
                (self, 'width'),
            ),
        )

    def compile( self, mode  ):
        """Compile this geometry node to display-list
        
        Initial code is taken from the PyOpenGL-Demo gears.py
        which was in the Public Domain and converted multiple 
        times since then.
        """
        dl = displaylist.DisplayList()
        dl.start()
        try:
            self.gear(
                self.inner_radius,
                self.outer_radius,
                self.width,
                self.teeth,
                self.tooth_depth,
            )
            holder = mode.cache.holder(self, dl)
            for name in ('inner_radius','outer_radius','width','teeth','tooth_depth'):
                holder.depend( self, name )
            return dl
        finally:
            dl.end()
    @classmethod
    def gear( cls, inner_radius, outer_radius, width, teeth, tooth_depth):
        """Generic renderer (not necessarily display-list based"""
        r0 = inner_radius
        r1 = outer_radius - tooth_depth/2.0
        r2 = outer_radius + tooth_depth/2.0    
        da = 2.0*pi / teeth / 4.0
        
        glShadeModel(GL_FLAT)  
        glNormal3f(0.0, 0.0, 1.0)

        # draw front face
        glBegin(GL_QUAD_STRIP)
        for i in range(teeth + 1):
            angle = i * 2.0 * pi / teeth
            glVertex3f(r0*cos(angle), r0*sin(angle), width*0.5)
            glVertex3f(r1*cos(angle), r1*sin(angle), width*0.5)
            glVertex3f(r0*cos(angle), r0*sin(angle), width*0.5)
            glVertex3f(r1*cos(angle+3*da), r1*sin(angle+3*da), width*0.5)
        glEnd()

        # draw front sides of teeth
        glBegin(GL_QUADS)
        da = 2.0*pi / teeth / 4.0
        for i in range(teeth):
            angle = i * 2.0*pi / teeth
            glVertex3f(r1*cos(angle),      r1*sin(angle),      width*0.5)
            glVertex3f(r2*cos(angle+da),   r2*sin(angle+da),   width*0.5)
            glVertex3f(r2*cos(angle+2*da), r2*sin(angle+2*da), width*0.5)
            glVertex3f(r1*cos(angle+3*da), r1*sin(angle+3*da), width*0.5)
        glEnd()

        glNormal3f(0.0, 0.0, -1.0)

        # draw back face
        glBegin(GL_QUAD_STRIP)
        for i in range(teeth + 1):
            angle = i * 2.0*pi / teeth
            glVertex3f(r1*cos(angle), r1*sin(angle), -width*0.5)
            glVertex3f(r0*cos(angle), r0*sin(angle), -width*0.5)
            glVertex3f(r1*cos(angle+3*da), r1*sin(angle+3*da),-width*0.5)
            glVertex3f(r0*cos(angle), r0*sin(angle), -width*0.5)
        glEnd()

        # draw back sides of teeth
        glBegin(GL_QUADS)
        da = 2.0*pi / teeth / 4.0
        for i in range(teeth):
            angle = i * 2.0*pi / teeth        
            glVertex3f(r1*cos(angle+3*da), r1*sin(angle+3*da),-width*0.5)
            glVertex3f(r2*cos(angle+2*da), r2*sin(angle+2*da),-width*0.5)
            glVertex3f(r2*cos(angle+da),   r2*sin(angle+da),  -width*0.5)
            glVertex3f(r1*cos(angle),      r1*sin(angle),     -width*0.5)
        glEnd()

        # draw outward faces of teeth
        glBegin(GL_QUAD_STRIP);
        for i in range(teeth):
            angle = i * 2.0*pi / teeth        
            glVertex3f(r1*cos(angle), r1*sin(angle),  width*0.5)
            glVertex3f(r1*cos(angle), r1*sin(angle), -width*0.5)
            u = r2*cos(angle+da) - r1*cos(angle)
            v = r2*sin(angle+da) - r1*sin(angle)
            len = sqrt(u*u + v*v)
            u = u / len
            v = v / len
            glNormal3f(v, -u, 0.0)
            glVertex3f(r2*cos(angle+da),   r2*sin(angle+da),   width*0.5)
            glVertex3f(r2*cos(angle+da),   r2*sin(angle+da),  -width*0.5)
            glNormal3f(cos(angle), sin(angle), 0.0)
            glVertex3f(r2*cos(angle+2*da), r2*sin(angle+2*da), width*0.5)
            glVertex3f(r2*cos(angle+2*da), r2*sin(angle+2*da),-width*0.5)
            u = r1*cos(angle+3*da) - r2*cos(angle+2*da)
            v = r1*sin(angle+3*da) - r2*sin(angle+2*da)
            glNormal3f(v, -u, 0.0)
            glVertex3f(r1*cos(angle+3*da), r1*sin(angle+3*da), width*0.5)
            glVertex3f(r1*cos(angle+3*da), r1*sin(angle+3*da),-width*0.5)
            glNormal3f(cos(angle), sin(angle), 0.0)

        glVertex3f(r1*cos(0), r1*sin(0), width*0.5)
        glVertex3f(r1*cos(0), r1*sin(0), -width*0.5)

        glEnd()

        glShadeModel(GL_SMOOTH)

        # draw inside radius cylinder
        glBegin(GL_QUAD_STRIP)
        for i in range(teeth + 1):
            angle = i * 2.0*pi / teeth;
            glNormal3f(-cos(angle), -sin(angle), 0.0)
            glVertex3f(r0*cos(angle), r0*sin(angle), -width*0.5)
            glVertex3f(r0*cos(angle), r0*sin(angle), width*0.5)
        glEnd()