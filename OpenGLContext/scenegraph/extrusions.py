"""GLE-based extrusion node-types"""
from vrml import node, field
from vrml.vrml97 import nodetypes
from vrml import cache
from OpenGLContext import displaylist
from OpenGL.GLE import *
from math import pi
import logging
log = logging.getLogger( __name__ )

RAD_TO_DEG = 360/pi

class GLEGeom( nodetypes.Geometry, node.Node ):
    """Base class for GLE geometry types

    Provides the common operations and data seen in
    the GLE geometry types.
    
    Attributes:
        textureMode -- specification of texture-coordinate
            generation mode to be passed to GLE, include:
                "mod" -- if present, use model view coordinates
                "ver"/"norm" -- vertex/normal mode
                "flat"/"cyl"/"sphere" -- flat, cylinder or
                    spherical coordinate generation
            See:
                http://pyopengl.sourceforge.net/documentation/manual/gleTextureMode.3GLE.xml
            for semantics of the various modes.
    """
    sides = field.newField( 'sides', 'SFInt32', 1, 32 )
    textureMode = field.newField( 'textureMode', 'SFString', 1, "")
    def render (
            self,
            visible = 1, # can skip normals and textures if not
            lit = 1, # can skip normals if not
            textured = 1, # can skip textureCoordinates if not
            transparent = 0, # need to sort triangle geometry...
            mode = None, # the renderpass object
        ):
        """Render the geometry"""
        # do we have a cached array-geometry?
        dl = mode.cache.getData(self)
        if not dl:
            dl = self.compile( mode=mode )
        dl()
        return 1
        
    def compile( self, mode=None ):
        """Compile the geometry as a display-list"""
        dl = displaylist.DisplayList()
        dl.start()
        try:
            self.do()
            holder = mode.cache.holder(self, dl)
            return dl
        finally:
            dl.end()
    
    textureFormats = (
        ('mod', (
            ('vert', (
                ('flat', GLE_TEXTURE_VERTEX_MODEL_FLAT),
                ('cyl', GLE_TEXTURE_VERTEX_MODEL_CYL),
                ('sph', GLE_TEXTURE_VERTEX_MODEL_SPH),
            )),
            ('norm', (
                ('flat', GLE_TEXTURE_NORMAL_MODEL_FLAT),
                ('cyl', GLE_TEXTURE_NORMAL_MODEL_CYL),
                ('sph', GLE_TEXTURE_NORMAL_MODEL_SPH),
            )),
        )),
        ('', (
            ('vert', (
                ('flat', GLE_TEXTURE_VERTEX_FLAT),
                ('cyl', GLE_TEXTURE_VERTEX_CYL),
                ('sph', GLE_TEXTURE_VERTEX_SPH),
            )),
            ('norm', (
                ('flat', GLE_TEXTURE_NORMAL_FLAT),
                ('cyl', GLE_TEXTURE_NORMAL_CYL),
                ('sph', GLE_TEXTURE_NORMAL_SPH),
            )),
        )),
    )
    def do( self ):
        """Do the low-level rendering"""
        if self.textureMode:
            mode = GLE_TEXTURE_ENABLE
            format = self.textureMode.lower()
            table = self.textureFormats
            while table and isinstance(table, tuple):
                found = 0
                for (name, curTable) in table:
                    if format.find(name) > -1:
                        table = curTable
                        found = 1
                if not found:
                    log.warn( """Texturemode %s wasn't recognisable for node %s, expected one of %s, didn't find any""", self.textureMode, self, [x[0] for x in table])
                    break
            if not isinstance(table,tuple):
                gleTextureMode( mode | table )
        gleSetNumSides(self.sides)

class Lathe( GLEGeom ):
    """Lathe of contour around a spiral (or circle)

    contour -- the shape being swept
    normals -- normals to the contour
    up -- the 3D vector orienting the contour
    startRadius -- initial radius of the spiral
    deltaRadius -- change in radius of spiral for each spiral rotation
    startZ -- starting Z coordinate for the spiral
    deltaZ -- change in Z coordinate for each spiral rotation
    startAngle -- angle at which spiral starts (in radians)
    totalAngle -- angle included in the spiral (in radians)
    
    sides -- number of divisions in a rotation

    http://pyopengl.sourceforge.net/documentation/manual/gleLathe.3GLE.xml
    """
    contour = field.newField( 'contour', 'MFVec2f', 1, list )
    normals = field.newField( 'normals', 'MFVec2f', 1, list )
    up = field.newField( 'up', 'SFVec3f', 1, (1,0,0) )
    startRadius = field.newField( 'startRadius', 'SFFloat', 1, 1.0 )
    deltaRadius = field.newField( 'deltaRadius', 'SFFloat', 1, 0.0 )
    startZ = field.newField( 'startZ', 'SFFloat', 1, 0.0 )
    deltaZ = field.newField( 'deltaZ', 'SFFloat', 1, 0.0 )
    startAngle = field.newField( 'startAngle', 'SFFloat', 1, 0.0 )
    totalAngle = field.newField( 'totalAngle', 'SFFloat', 1, pi )
    def do( self ):
        super( Lathe, self).do()
        gleLathe(
            self.contour.astype('d'),
            self.normals.astype('d'),
            self.up.astype('d'),
            self.startRadius, # start radius for spiral
            self.deltaRadius, # delta radius for spiral
            self.startZ, # start Z for spiral
            self.deltaZ, # delta Z for spiral
            None,# start AFINE transform,
            None, # delta AFINE transform
            self.startAngle*RAD_TO_DEG, # starting angle
            self.totalAngle*RAD_TO_DEG, # total angle in degrees,
        )

class Screw( GLEGeom ):
    """Linear extrusion with twisting

    contour -- the shape being swept
    normals -- normals to the contour
    up -- the 3D vector orienting the contour
    startZ -- starting Z coordinate for the spiral
    endZ -- ending Z coordinate for each spiral rotation
    totalAngle -- total angle of rotation across length (radians)
    
    sides -- number of divisions in a rotation

    http://pyopengl.sourceforge.net/documentation/manual/gleScrew.3GLE.xml
    """
    contour = field.newField( 'contour', 'MFVec2f', 1, list )
    normals = field.newField( 'normals', 'MFVec2f', 1, list )
    up = field.newField( 'up', 'SFVec3f', 1, (1,0,0) )
    startZ = field.newField( 'startZ', 'SFFloat', 1, 0.0 )
    endZ = field.newField( 'endZ', 'SFFloat', 1, 0.0 )
    totalAngle = field.newField( 'totalAngle', 'SFFloat', 1, pi )
    def do( self ):
        super( Screw, self).do()
        gleScrew(
            self.contour.astype('d'),
            self.normals.astype('d'),
            self.up.astype('d'),
            self.startZ, # z start
            self.endZ, # z end
            self.totalAngle*RAD_TO_DEG, # rotations,
        )
class Spiral( GLEGeom ):
    """Banked spiral geometry

    contour -- the shape being swept
    normals -- normals to the contour
    up -- the 3D vector orienting the contour
    startRadius -- initial radius of the spiral
    deltaRadius -- change in radius of spiral for each spiral rotation
    startZ -- starting Z coordinate for the spiral
    deltaZ -- change in Z coordinate for each spiral rotation
    startAngle -- angle at which spiral starts (in radians)
    totalAngle -- angle included in the spiral (in radians)
    
    sides -- number of divisions in a rotation

    http://pyopengl.sourceforge.net/documentation/manual/gleSpiral.3GLE.xml
    """
    contour = field.newField( 'contour', 'MFVec2f', 1, list )
    normals = field.newField( 'normals', 'MFVec2f', 1, list )
    up = field.newField( 'up', 'SFVec3f', 1, (1,0,0) )
    startRadius = field.newField( 'startRadius', 'SFFloat', 1, 1.0 )
    deltaRadius = field.newField( 'deltaRadius', 'SFFloat', 1, 0.0 )
    startZ = field.newField( 'startZ', 'SFFloat', 1, 0.0 )
    deltaZ = field.newField( 'deltaZ', 'SFFloat', 1, 0.0 )
    startAngle = field.newField( 'startAngle', 'SFFloat', 1, 0.0 )
    totalAngle = field.newField( 'totalAngle', 'SFFloat', 1, pi )
    def do( self ):
        super( Spiral, self).do()
        gleSpiral(
            self.contour.astype('d'),
            self.normals.astype('d'),
            self.up.astype('d'),
            self.startRadius, # start radius for spiral
            self.deltaRadius, # delta radius for spiral
            self.startZ, # start Z for spiral
            self.deltaZ, # delta Z for spiral
            None,# start AFINE transform,
            None, # delta AFINE transform
            self.startAngle*RAD_TO_DEG, # starting angle
            self.totalAngle*RAD_TO_DEG, # total angle in degrees,
        )
