#! /usr/bin/env python
"""Retrieve OpenGL state values and print to console"""
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
import string

from OpenGLContext.scenegraph import basenodes

class TestContext( BaseContext ):
    def OnInit( self ):
        self.text = basenodes.Text( )
        self.sg = basenodes.sceneGraph(
            children = [
                basenodes.Transform(
                    scale = (.5,.5,.5),
                    translation = (-3,0,0),
                    children = [
                        basenodes.Shape(
                            geometry = self.text,
                        ),
                    ],
                )
            ],
        )
        self.strings = []
        self.strings.append( 'Integers/Booleans:' )
        for name, argument, description in booleanarguments:
            # really should make "glGet" an alias so this doesn't look so weird...
            result = glGetIntegerv( argument )
            self.strings.append( '  %s -> %s' % (name, result ) )
        self.strings.append( 'Doubles/Floats:' )
        for name, argument, description in doublearguments:
            result1,result2 = glGetDoublev( argument ), glGetFloatv( argument )
            self.strings.append( '  %s -> %s' % (name, result1 ) )
        
        self.strings.append( 'Strings:' )
        for name, argument, description in stringarguments:
            # really should make "glGet" an alias so this doesn't look so weird...
            result = glGetString( argument )
            self.strings.append( '  %s -> %s' % (name, result ) )
        self.strings.append( 'Extensions:' )
        for extension in glGetString( GL_EXTENSIONS).split():
            self.strings.append( '  %s'%( extension ) )
        self.text.string = self.strings

from OpenGL.GL import *

doublearguments = [
    ('GL_COLOR_CLEAR_VALUE',GL_COLOR_CLEAR_VALUE,'params returns four values:  the red, green, blue, and alpha values used to clear the color buffers. Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glClearColor.'),
##	('GL_COLOR_MATRIX_SGI',GL_COLOR_MATRIX_SGI,'params returns sixteen values:  the color matrix on the top of the color matrix stack.  See glPushMatrix, glPixelTransfer.'),
    ('GL_CURRENT_COLOR',GL_CURRENT_COLOR,'params returns four values:  the red, green, blue, and alpha values of the current color. Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glColor.'),
    ('GL_CURRENT_NORMAL',GL_CURRENT_NORMAL,'params returns three values:  the x, y, and z values of the current normal.  Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glNormal.'),
    ('GL_CURRENT_RASTER_COLOR',GL_CURRENT_RASTER_COLOR,'params returns four values:  the red, green, blue, and alpha values of the current raster position.  Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glRasterPos.'),
    ('GL_CURRENT_RASTER_DISTANCE',GL_CURRENT_RASTER_DISTANCE,'params returns one value, the distance from the eye to the current raster position.  See glRasterPos.'),
    ('GL_CURRENT_RASTER_POSITION',GL_CURRENT_RASTER_POSITION,'params returns four values:  the x, y, z, and w components of the current raster position.  x, y, and z are in window coordinates, and w is in clip coordinates.  See glRasterPos.'),
    ('GL_CURRENT_RASTER_TEXTURE_COORDS',GL_CURRENT_RASTER_TEXTURE_COORDS,'params returns four values:  the s, t, r, and q current raster texture coordinates.  See glRasterPos and glTexCoord.'),
    ('GL_CURRENT_RASTER_POSITION_VALID',GL_CURRENT_RASTER_POSITION_VALID,'params returns a single Boolean value indicating whether the current raster position is valid. See glRasterPos.'),
    ('GL_CURRENT_TEXTURE_COORDS',GL_CURRENT_TEXTURE_COORDS,'params returns four values:  the s, t, r, and q current texture coordinates.  See glTexCoord.'),
    ('GL_DEPTH_BIAS',GL_DEPTH_BIAS,'params returns one value, the depth bias factor used during pixel transfers.  See glPixelTransfer.'),
    ('GL_DEPTH_RANGE',GL_DEPTH_RANGE,'params returns two values:  the near and far mapping limits for the depth buffer.  Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glDepthRange.'),
    ('GL_DEPTH_SCALE',GL_DEPTH_SCALE,'params returns one value, the depth scale factor used during pixel transfers.  See glPixelTransfer.'),
    ('GL_FOG_COLOR',GL_FOG_COLOR,'params returns four values:  the red, green, blue, and alpha components of the fog color. Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glFog.'),
    ('GL_FOG_DENSITY',GL_FOG_DENSITY,'params returns one value, the fog density parameter.  See glFog.'),
    ('GL_FOG_END',GL_FOG_END,'params returns one value, the end factor for the linear fog equation.  See glFog.'),
##	('GL_FOG_FUNC_POINTS_SGIS',GL_FOG_FUNC_POINTS_SGIS,'params returns one value, the number of points in the current custom fog blending function. See glFog and glFogFuncSGIS.'),
##	('GL_FOG_FUNC_SGIS',GL_FOG_FUNC_SGIS,'params returns an array of fog blending function control points.  Each control point consists of two values, an eye-space distance and a blending factor, in that order.  The control points are listed in order of increasing eye-space distance.  The number of control points may be queried by glGet with argument GL_FOG_FUNC_POINTS_SGIS. See glFog and glFogFuncSGIS.'),
##	('GL_FOG_OFFSET_VALUE_SGIX',GL_FOG_OFFSET_VALUE_SGIX,'params returns four values, a reference point (X,Y,Z) in eye coordinates, and a Z offset in eye coordinates. See glFog.'),
    ('GL_FOG_START',GL_FOG_START,'params returns one value, the start factor for the linear fog equation. See glFog.'),
    ('GL_GREEN_SCALE',GL_GREEN_SCALE,'params returns one value, the green scale factor used during pixel transfers.  See glPixelTransfer.'),
    ('GL_LIGHT_MODEL_AMBIENT',GL_LIGHT_MODEL_AMBIENT,'params returns four values:  the red, green, blue, and alpha components of the ambient intensity of the entire scene.  Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glLightModel.'),
    ('GL_LINE_WIDTH',GL_LINE_WIDTH,'params returns one value, the line width as specified with glLineWidth.'),
    ('GL_MODELVIEW_MATRIX',GL_MODELVIEW_MATRIX,'params returns sixteen values:  the modelview matrix on the top of the modelview matrix stack. See glPushMatrix.'),
    ('GL_POINT_SIZE',GL_POINT_SIZE,'params returns one value, the point size as specified by glPointSize.'),
    ('GL_POINT_SIZE_RANGE',GL_POINT_SIZE_RANGE,'params returns two values:  the smallest and largest supported sizes for antialiased points. See glPointSize.'),
    ('GL_PROJECTION_MATRIX',GL_PROJECTION_MATRIX,'params returns sixteen values:  the projection matrix on the top of the projection matrix stack. See glPushMatrix.'),
    ('GL_TEXTURE_MATRIX',GL_TEXTURE_MATRIX,'params returns sixteen values:  the texture matrix on the top of the texture matrix stack. See glPushMatrix.'),
    ('GL_ZOOM_X',GL_ZOOM_X,'params returns one value, the x pixel zoom factor.  See glPixelZoom.'),
    ('GL_ZOOM_Y',GL_ZOOM_Y,'params returns one value, the y pixel zoom factor.  See glPixelZoom.'),
]

booleanarguments = [
    ('GL_AUTO_NORMAL',GL_AUTO_NORMAL,'params returns a single Boolean value indicating whether 2-D map evaluation automatically generates surface normals.  See glMap2.'),
    ('GL_BLEND',GL_BLEND,'params returns a single Boolean value indicating whether blending is enabled.  See glBlendFunc.'),
##	('GL_BLEND_COLOR_EXT',GL_BLEND_COLOR_EXT,'params returns four values, the red, green, blue, and alpha values which are the components of the blend color.  See glBlendColorEXT.'),
##	('GL_CLIP_PLANEi',GL_CLIP_PLANEi,'params returns a single Boolean value indicating whether the specified clipping plane is enabled. See glClipPlane.'),
    ('GL_COLOR_MATERIAL',GL_COLOR_MATERIAL,'params returns a single Boolean value indicating whether one or more material parameters are tracking the current color.  See glColorMaterial.'),
##	('GL_COLOR_TABLE_SGI',GL_COLOR_TABLE_SGI,'params returns a single Boolean value indicating whether colors are passed through a lookup table before being used by convolution.  See glColorTableSGI.'),
    ('GL_COLOR_WRITEMASK',GL_COLOR_WRITEMASK,'params returns four Boolean values:  the red, green, blue, and alpha write enables for the color buffers.  See glColorMask.'),
##	('GL_CONVOLUTION_1D_EXT',GL_CONVOLUTION_1D_EXT,'params returns a single Boolean value indicating whether one-dimensional convolution will be performed during pixel transfers.  See glConvolutionFilter1DEXT.'),
##	('GL_CONVOLUTION_2D_EXT',GL_CONVOLUTION_2D_EXT,'params returns a single Boolean value indicating whether two-dimensional convolution will be performed during pixel transfers.  See glConvolutionFilter2DEXT.'),
    ('GL_CULL_FACE',GL_CULL_FACE,'params returns a single Boolean value indicating whether polygon culling is enabled.  See glCullFace.'),
    ('GL_DEPTH_TEST',GL_DEPTH_TEST,'params returns a single Boolean value indicating whether depth testing of fragments is enabled. See glDepthFunc and glDepthRange.'),
    ('GL_DEPTH_WRITEMASK',GL_DEPTH_WRITEMASK,'params returns a single Boolean value indicating if the depth buffer is enabled for writing.  See glDepthMask.'),

##	('GL_DETAIL_TEXTURE_2D_BINDING_SGIS',GL_DETAIL_TEXTURE_2D_BINDING_SGIS,'params returns a single value, the name of the detail texture bound to GL_DETAIL_TEXTURE_2D_SGIS (or zero if there is none).  See glDetailTexFuncSGIS.'),

    ('GL_DITHER',GL_DITHER,'params returns a single Boolean value indicating whether dithering of fragment colors and indices is enabled.'),
    ('GL_DOUBLEBUFFER',GL_DOUBLEBUFFER,'params returns a single Boolean value indicating whether double buffering is supported.'),

    ('GL_DRAW_BUFFER',GL_DRAW_BUFFER,'params returns one value, a symbolic constant indicating which buffers are being drawn to. See glDrawBuffer.'),

    ('GL_EDGE_FLAG',GL_EDGE_FLAG,'params returns a single Boolean value indication whether the current edge flag is true or false. See glEdgeFlag.'),
    ('GL_FOG',GL_FOG,'params returns a single Boolean value indicating whether fogging is enabled.  See glFog.'),

    ('GL_FOG_HINT',GL_FOG_HINT,'params returns one value, a symbolic constant indicating the mode of the fog hint.  See glHint.'),
    ('GL_FOG_INDEX',GL_FOG_INDEX,'params returns one value, the fog color index. See glFog.'),
    ('GL_FOG_MODE',GL_FOG_MODE,'params returns one value, a symbolic constant indicating which fog equation is selected.  See glFog.'),

##	('GL_FOG_OFFSET_SGIX',GL_FOG_OFFSET_SGIX,'params returns a single Boolean value indicating whether fog offset is enabled.  See glFog.'),

    ('GL_FRONT_FACE',GL_FRONT_FACE,'params returns one value, a symbolic constant indicating whether clockwise or counterclockwise polygon winding is treated as front-facing.  See glFrontFace.'),
    ('GL_GREEN_BIAS',GL_GREEN_BIAS,'params returns one value, the green bias factor used during pixel transfers.'),
    ('GL_GREEN_BITS',GL_GREEN_BITS,'params returns one value, the number of green bitplanes in each color buffer.'),
##	('GL_HISTOGRAM_EXT',GL_HISTOGRAM_EXT,'params returns a single Boolean value indicating whether histogramming is enabled.  See glHistogramEXT.'),
    ('GL_INDEX_BITS',GL_INDEX_BITS,'params returns one value, the number of bitplanes in each color index buffer.'),
    ('GL_INDEX_CLEAR_VALUE',GL_INDEX_CLEAR_VALUE,'params returns one value, the color index used to clear the color index buffers.  See glClearIndex.'),

    ('GL_INDEX_MODE',GL_INDEX_MODE,'params returns a single Boolean value indicating whether the GL is in color index mode (true) or RGBA mode (false).'),

    ('GL_INDEX_OFFSET',GL_INDEX_OFFSET,'params returns one value, the offset added to color and stencil indices during pixel transfers.  See glPixelTransfer.'),
    ('GL_INDEX_SHIFT',GL_INDEX_SHIFT,'params returns one value, the amount that color and stencil indices are shifted during pixel transfers.  See glPixelTransfer.'),
    ('GL_INDEX_WRITEMASK',GL_INDEX_WRITEMASK,'params returns one value, a mask indicating which bitplanes of each color index buffer can be written.  See glIndexMask.'),

##	('GL_INTERLACE_SGIX',GL_INTERLACE_SGIX,'params returns a single Boolean value indicating whether glCopyPixels and glCopyTexSubImage2DEXT skip every other line in the destination pixel array.  See glCopyPixels and glCopyTexSubImage2DEXT.'),
##	('GL_LIGHTi',GL_LIGHTi,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT0',GL_LIGHT0,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT1',GL_LIGHT1,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT2',GL_LIGHT2,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT3',GL_LIGHT3,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT4',GL_LIGHT4,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT5',GL_LIGHT5,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT6',GL_LIGHT6,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHT7',GL_LIGHT7,'params returns a single Boolean value indicating whether the specified light is enabled.  See glLight and glLightModel.'),
    ('GL_LIGHTING',GL_LIGHTING,'params returns a single Boolean value indicating whether lighting is enabled.  See glLightModel.'),
    ('GL_LIGHT_MODEL_LOCAL_VIEWER',GL_LIGHT_MODEL_LOCAL_VIEWER,'params returns a single Boolean value indicating whether specular reflection calculations treat the viewer as being local to the scene.  See glLightModel.'),
    ('GL_LIGHT_MODEL_TWO_SIDE',GL_LIGHT_MODEL_TWO_SIDE,'params returns a single Boolean value indicating whether separate materials are used to compute lighting for front- and back-facing polygons. See glLightModel.'),
    ('GL_LINE_SMOOTH',GL_LINE_SMOOTH,'params returns a single Boolean value indicating whether antialiasing of lines is enabled.  See glLineWidth.'),
    
    ('GL_LINE_SMOOTH_HINT',GL_LINE_SMOOTH_HINT,'params returns one value, a symbolic constant indicating the mode of the line antialiasing hint.  See glHint.'),
    
    ('GL_LINE_STIPPLE',GL_LINE_STIPPLE,'params returns a single Boolean value indicating whether stippling of lines is enabled.  See glLineStipple.'),

    ('GL_LINE_STIPPLE_PATTERN',GL_LINE_STIPPLE_PATTERN,'params returns one value, the 16-bit line stipple pattern. See glLineStipple.'),
    ('GL_LINE_STIPPLE_REPEAT',GL_LINE_STIPPLE_REPEAT,'params returns one value, the line stipple repeat factor.  See glLineStipple.'),
    ('GL_LINE_WIDTH_GRANULARITY',GL_LINE_WIDTH_GRANULARITY,'params returns one value, the width difference between adjacent supported widths for antialiased lines.  See glLineWidth.'),
    ('GL_LINE_WIDTH_RANGE',GL_LINE_WIDTH_RANGE,'params returns two values:  the smallest and largest supported widths for antialiased lines. See glLineWidth.'),
    ('GL_LIST_BASE',GL_LIST_BASE,'params returns one value, the base offset added to all names in arrays presented to glCallLists. See glListBase.'),
    ('GL_LIST_INDEX',GL_LIST_INDEX,'params returns one value, the name of the display list currently under construction.  Zero is returned if no display list is currently under construction.  See glNewList.'),
    ('GL_LIST_MODE',GL_LIST_MODE,'params returns one value, a symbolic constant indicating the construction mode of the display list currently being constructed.  See glNewList.'),

    ('GL_LOGIC_OP',GL_LOGIC_OP,'params returns a single Boolean value indicating whether fragment indexes are merged into the framebuffer using a logical operation.  See glLogicOp.'),

    ('GL_LOGIC_OP_MODE',GL_LOGIC_OP_MODE,'params returns one value, a symbolic constant indicating the selected logic operational mode. See glLogicOp.'),
    ('GL_MAP1_COLOR_4',GL_MAP1_COLOR_4,'params returns a single Boolean value indicating whether 1D evaluation generates colors.  See glMap1.'),

    ('GL_MAP1_GRID_DOMAIN',GL_MAP1_GRID_DOMAIN,"params returns two values:  the endpoints of the 1-D map's grid domain.  See glMapGrid."),
    ('GL_MAP1_GRID_SEGMENTS',GL_MAP1_GRID_SEGMENTS,"params returns one value, the number of partitions in the 1-D map's grid domain. See glMapGrid."),

    ('GL_MAP1_INDEX',GL_MAP1_INDEX,'params returns a single Boolean value indicating whether 1D evaluation generates color indices. See glMap1.'),
    ('GL_MAP1_NORMAL',GL_MAP1_NORMAL,'params returns a single Boolean value indicating whether 1D evaluation generates normals. See glMap1.'),
    ('GL_MAP1_TEXTURE_COORD_1',GL_MAP1_TEXTURE_COORD_1,'params returns a single Boolean value indicating whether 1D evaluation generates 1D texture coordinates.  See glMap1.'),
    ('GL_MAP1_TEXTURE_COORD_2',GL_MAP1_TEXTURE_COORD_2,'params returns a single Boolean value indicating whether 1D evaluation generates 2D texture coordinates.  See glMap1.'),
    ('GL_MAP1_TEXTURE_COORD_3',GL_MAP1_TEXTURE_COORD_3,'params returns a single Boolean value indicating whether 1D evaluation generates 3D texture coordinates.  See glMap1.'),
    ('GL_MAP1_TEXTURE_COORD_4',GL_MAP1_TEXTURE_COORD_4,'params returns a single Boolean value indicating whether 1D evaluation generates 4D texture coordinates.  See glMap1.'),
    ('GL_MAP1_VERTEX_3',GL_MAP1_VERTEX_3,'params returns a single Boolean value indicating whether 1D evaluation generates 3D vertex coordinates.  See glMap1.'),
    ('GL_MAP1_VERTEX_4',GL_MAP1_VERTEX_4,'params returns a single Boolean value indicating whether 1D evaluation generates 4D vertex coordinates.  See glMap1.'),
    ('GL_MAP2_COLOR_4',GL_MAP2_COLOR_4,'params returns a single Boolean value indicating whether 2D evaluation generates colors.  See glMap2.'),

    ('GL_MAP2_GRID_DOMAIN',GL_MAP2_GRID_DOMAIN,"params returns four values:  the endpoints of the 2-D map's i and j grid domains.  See glMapGrid."),
    ('GL_MAP2_GRID_SEGMENTS',GL_MAP2_GRID_SEGMENTS,"params returns two values:  the number of partitions in the 2-D map's i and j grid domains. See glMapGrid."),

    ('GL_MAP2_INDEX',GL_MAP2_INDEX,'params returns a single Boolean value indicating whether 2D evaluation generates color indices. See glMap2.'),
    ('GL_MAP2_NORMAL',GL_MAP2_NORMAL,'params returns a single Boolean value indicating whether 2D evaluation generates normals. See glMap2.'),
    ('GL_MAP2_TEXTURE_COORD_1',GL_MAP2_TEXTURE_COORD_1,'params returns a single Boolean value indicating whether 2D evaluation generates 1D texture coordinates.  See glMap2.'),
    ('GL_MAP2_TEXTURE_COORD_2',GL_MAP2_TEXTURE_COORD_2,'params returns a single Boolean value indicating whether 2D evaluation generates 2D texture coordinates.  See glMap2.'),
    ('GL_MAP2_TEXTURE_COORD_3',GL_MAP2_TEXTURE_COORD_3,'params returns a single Boolean value indicating whether 2D evaluation generates 3D texture coordinates.  See glMap2.'),
    ('GL_MAP2_TEXTURE_COORD_4',GL_MAP2_TEXTURE_COORD_4,'params returns a single Boolean value indicating whether 2D evaluation generates 4D texture coordinates.  See glMap2.'),
    ('GL_MAP2_VERTEX_3',GL_MAP2_VERTEX_3,'params returns a single Boolean value indicating whether 2D evaluation generates 3D vertex coordinates.  See glMap2.'),
    ('GL_MAP2_VERTEX_4',GL_MAP2_VERTEX_4,'params returns a single Boolean value indicating whether 2D evaluation generates 4D vertex coordinates.  See glMap2.'),
    ('GL_MAP_COLOR',GL_MAP_COLOR,'params returns a single Boolean value indicating if colors and color indices are to be replaced by table lookup during pixel transfers.  See glPixelTransfer.'),
    ('GL_MAP_STENCIL',GL_MAP_STENCIL,'params returns a single Boolean value indicating if stencil indices are to be replaced by table lookup during pixel transfers.  See glPixelTransfer.'),

    ('GL_MATRIX_MODE',GL_MATRIX_MODE,'params returns one value, a symbolic constant indicating which matrix stack is currently the target of all matrix operations. See glMatrixMode.'),

##	('GL_MAX_3D_TEXTURE_SIZE',GL_MAX_3D_TEXTURE_SIZE,'params returns one value, the maximum width, height, or depth of any texture image (without borders).  See glTexImage3DEXT.'),
    ('GL_MAX_ATTRIB_STACK_DEPTH',GL_MAX_ATTRIB_STACK_DEPTH,'params returns one value, the maximum supported depth of the attribute stack.  See glPushAttrib.'),
    ('GL_MAX_CLIP_PLANES',GL_MAX_CLIP_PLANES,'params returns one value, the maximum number of application-defined clipping planes.  See glClipPlane.'),
##	('GL_MAX_CLIPMAP_DEPTH_SGIX',GL_MAX_CLIPMAP_DEPTH_SGIX,'params returns one value, the maximum number of levels permitted in a clipmap.  See glTexParameter.'),
##	('GL_MAX_COLOR_MATRIX_STACK_DEPTH_SGI',GL_MAX_COLOR_MATRIX_STACK_DEPTH_SGI,'params returns one value, the maximum supported depth of the color matrix stack. See glPushMatrix, glPixelTransfer.'),
    ('GL_MAX_EVAL_ORDER',GL_MAX_EVAL_ORDER,'params returns one value, the maximum equation order supported by 1-D and 2-D evaluators.  See glMap1 and glMap2.'),
##	('GL_MAX_FOG_FUNC_POINTS_SGIS',GL_MAX_FOG_FUNC_POINTS_SGIS,'params returns one value, the maximum number of control points supported in custom fog blending functions.  See glFog and glFogFuncSGIS.'),
    ('GL_MAX_LIGHTS',GL_MAX_LIGHTS,'params returns one value, the maximum number of lights.  See glLight.'),
    ('GL_MAX_LIST_NESTING',GL_MAX_LIST_NESTING,'params returns one value, the maximum recursion depth allowed during display-list traversal. See glCallList.'),
    ('GL_MAX_MODELVIEW_STACK_DEPTH',GL_MAX_MODELVIEW_STACK_DEPTH,'params returns one value, the maximum supported depth of the modelview matrix stack.  See glPushMatrix.'),
    ('GL_MAX_NAME_STACK_DEPTH',GL_MAX_NAME_STACK_DEPTH,'params returns one value, the maximum supported depth of the selection name stack.  See glPushName.'),
    ('GL_MAX_PIXEL_MAP_TABLE',GL_MAX_PIXEL_MAP_TABLE,'params returns one value, the maximum supported size of a glPixelMap lookup table.  See glPixelMap.'),
    ('GL_MAX_PROJECTION_STACK_DEPTH',GL_MAX_PROJECTION_STACK_DEPTH,'params returns one value, the maximum supported depth of the projection matrix stack.  See glPushMatrix.'),
    ('GL_MAX_TEXTURE_SIZE',GL_MAX_TEXTURE_SIZE,'params returns one value, the maximum width or height of any texture image (without borders). See glTexImage1D and glTexImage2D.'),
    ('GL_MAX_TEXTURE_STACK_DEPTH',GL_MAX_TEXTURE_STACK_DEPTH,'params returns one value, the maximum supported depth of the texture matrix stack.  See glPushMatrix.'),
    ('GL_MAX_VIEWPORT_DIMS',GL_MAX_VIEWPORT_DIMS,'params returns two values:  the maximum supported width and height of the viewport.  See glViewport.'),
##	('GL_MINMAX_EXT',GL_MINMAX_EXT,'params returns a single Boolean value indicating whether the pixel transfer min/max computation is enabled.  See glMinmaxEXT.'),
    ('GL_MODELVIEW_STACK_DEPTH',GL_MODELVIEW_STACK_DEPTH,'params returns one value, the number of matrices on the modelview matrix stack.  See glPushMatrix.'),
##	('GL_MULTISAMPLE_SGIS',GL_MULTISAMPLE_SGIS,'params returns a single Boolean value indicating whether multisampling is enabled.  See glSamplePatternSGIS.'),
    ('GL_NAME_STACK_DEPTH',GL_NAME_STACK_DEPTH,'params returns one value, the number of names on the selection name stack.  See glPushMatrix.'),
    ('GL_NORMALIZE',GL_NORMALIZE,'params returns a single Boolean value indicating whether normals are automatically scaled to unit length after they have been transformed to eye coordinates.  See glNormal.'),
    ('GL_PACK_ALIGNMENT',GL_PACK_ALIGNMENT,'params returns one value, the byte alignment used for writing pixel data to memory.  See glPixelStore.'),
##	('GL_PACK_IMAGE_HEIGHT_EXT',GL_PACK_IMAGE_HEIGHT_EXT,'params returns one value, the image height used for writing (3D) pixel data to memory.  See glPixelStore.'),
    ('GL_PACK_LSB_FIRST',GL_PACK_LSB_FIRST,'params returns a single Boolean value indicating whether single-bit pixels being written to memory are written first to the least significant bit of each unsigned byte.  See glPixelStore.'),
    ('GL_PACK_ROW_LENGTH',GL_PACK_ROW_LENGTH,'params returns one value, the row length used for writing pixel data to memory.  See glPixelStore.'),
##	('GL_PACK_SKIP_IMAGES_EXT',GL_PACK_SKIP_IMAGES_EXT,'params returns one value, the number of 2D images skipped before the first pixel is written into memory.  See glPixelStore.'),
    ('GL_PACK_SKIP_PIXELS',GL_PACK_SKIP_PIXELS,'params returns one value, the number of pixel locations skipped before the first pixel is written into memory.  See glPixelStore.'),
    ('GL_PACK_SKIP_ROWS',GL_PACK_SKIP_ROWS,'params returns one value, the number of rows of pixel locations skipped before the first pixel is written into memory.  See glPixelStore.'),
    ('GL_PACK_SWAP_BYTES',GL_PACK_SWAP_BYTES,'params returns a single Boolean value indicating whether the bytes of two-byte and four-byte pixel indices and components are swapped before being written to memory. See glPixelStore.'),
    ('GL_PERSPECTIVE_CORRECTION_HINT',GL_PERSPECTIVE_CORRECTION_HINT,'params returns one value, a symbolic constant indicating the mode of the perspective correction hint. See glHint.'),
    ('GL_PIXEL_MAP_A_TO_A_SIZE',GL_PIXEL_MAP_A_TO_A_SIZE,'params returns one value, the size of the alpha-to-alpha pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_B_TO_B_SIZE',GL_PIXEL_MAP_B_TO_B_SIZE,'params returns one value, the size of the blue- to-blue pixel translation table. See glPixelMap.'),
    ('GL_PIXEL_MAP_G_TO_G_SIZE',GL_PIXEL_MAP_G_TO_G_SIZE,'params returns one value, the size of the green-to-green pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_I_TO_A_SIZE',GL_PIXEL_MAP_I_TO_A_SIZE,'params returns one value, the size of the index-to-alpha pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_I_TO_B_SIZE',GL_PIXEL_MAP_I_TO_B_SIZE,'params returns one value, the size of the index-to-blue pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_I_TO_G_SIZE',GL_PIXEL_MAP_I_TO_G_SIZE,'params returns one value, the size of the index-to-green pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_I_TO_I_SIZE',GL_PIXEL_MAP_I_TO_I_SIZE,'params returns one value, the size of the index-to-index pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_I_TO_R_SIZE',GL_PIXEL_MAP_I_TO_R_SIZE,'params returns one value, the size of the index-to-red pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_R_TO_R_SIZE',GL_PIXEL_MAP_R_TO_R_SIZE,'params returns one value, the size of the red- to-red pixel translation table.  See glPixelMap.'),
    ('GL_PIXEL_MAP_S_TO_S_SIZE',GL_PIXEL_MAP_S_TO_S_SIZE,'params returns one value, the size of the stencil-to-stencil pixel translation table.  See glPixelMap.'),
    ('GL_POINT_SIZE_GRANULARITY',GL_POINT_SIZE_GRANULARITY,'params returns one value, the size difference between adjacent supported sizes for antialiased points.  See glPointSize.'),
    ('GL_POINT_SMOOTH',GL_POINT_SMOOTH,'params returns a single Boolean value indicating whether antialiasing of points is enabled.  See glPointSize.'),
    ('GL_POINT_SMOOTH_HINT',GL_POINT_SMOOTH_HINT,'params returns one value, a symbolic constant indicating the mode of the point antialiasing hint.  See glHint.'),
    ('GL_POLYGON_MODE',GL_POLYGON_MODE,'params returns two values:  symbolic constants indicating whether front-facing and back-facing polygons are rasterized as points, lines, or filled polygons. See glPolygonMode.'),
##	('GL_POLYGON_OFFSET_EXT',GL_POLYGON_OFFSET_EXT,'params returns a single Boolean value indicating whether polygon offset is enabled.  See glPolygonOffsetEXT.'),
##	('GL_POLYGON_OFFSET_BIAS_EXT',GL_POLYGON_OFFSET_BIAS_EXT,'params returns one value, the constant which is added to the z value of each fragment generated when a polygon is rasterized.  See glPolygonOffsetEXT.'),
##	('GL_POLYGON_OFFSET_FACTOR_EXT',GL_POLYGON_OFFSET_FACTOR_EXT,'params returns one value, the scaling factor used to determine the variable offset which is added to the z value of each fragment generated when a polygon is rasterized.  See glPolygonOffsetEXT.'),
    ('GL_POLYGON_SMOOTH',GL_POLYGON_SMOOTH,'params returns a single Boolean value indicating whether antialiasing of polygons is enabled. See glPolygonMode.'),
    ('GL_POLYGON_SMOOTH_HINT',GL_POLYGON_SMOOTH_HINT,'params returns one value, a symbolic constant indicating the mode of the polygon antialiasing hint.  See glHint.'),
    ('GL_POLYGON_STIPPLE',GL_POLYGON_STIPPLE,'params returns a single Boolean value indicating whether stippling of polygons is enabled.  See glPolygonStipple.'),
##	('GL_POST_COLOR_MATRIX_ALPHA_BIAS_SGI',GL_POST_COLOR_MATRIX_ALPHA_BIAS_SGI,'params returns a single value, the bias term to be added to alpha immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_COLOR_MATRIX_ALPHA_SCALE_SGI',GL_POST_COLOR_MATRIX_ALPHA_SCALE_SGI,'params returns a single value, the scale factor to be applied to alpha immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_COLOR_MATRIX_BLUE_BIAS_SGI',GL_POST_COLOR_MATRIX_BLUE_BIAS_SGI,'params returns a single value, the bias term to be added to blue immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_COLOR_MATRIX_BLUE_SCALE_SGI',GL_POST_COLOR_MATRIX_BLUE_SCALE_SGI,'params returns a single value, the scale factor to be applied to blue immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_COLOR_MATRIX_COLOR_TABLE_SGI',GL_POST_COLOR_MATRIX_COLOR_TABLE_SGI,'params returns a single Boolean value indicating whether colors are passed through a lookup table before being processed by the histogram operation.  See glColorTableSGI.'),
##	('GL_POST_COLOR_MATRIX_GREEN_BIAS_SGI',GL_POST_COLOR_MATRIX_GREEN_BIAS_SGI,'params returns a single value, the bias term to be added to green immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_COLOR_MATRIX_GREEN_SCALE_SGI',GL_POST_COLOR_MATRIX_GREEN_SCALE_SGI,'params returns a single value, the scale factor to be applied to green immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_COLOR_MATRIX_RED_BIAS_SGI',GL_POST_COLOR_MATRIX_RED_BIAS_SGI,'params returns a single value, the bias term to be added to red immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_COLOR_MATRIX_RED_SCALE_SGI',GL_POST_COLOR_MATRIX_RED_SCALE_SGI,'params returns a single value, the scale factor to be applied to red immediately after multiplication by the top of the color matrix stack.  See glPixelTransfer.'),
##	('GL_POST_CONVOLUTION_ALPHA_BIAS_EXT',GL_POST_CONVOLUTION_ALPHA_BIAS_EXT,'params returns a single value, the bias term to be added to alpha immediately after convolution. See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_CONVOLUTION_ALPHA_SCALE_EXT',GL_POST_CONVOLUTION_ALPHA_SCALE_EXT,'params returns a single value, the scale factor to be applied to alpha immediately after convolution.  See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_CONVOLUTION_BLUE_BIAS_EXT',GL_POST_CONVOLUTION_BLUE_BIAS_EXT,'params returns a single value, the bias term to be added to blue immediately after convolution. See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_CONVOLUTION_BLUE_SCALE_EXT',GL_POST_CONVOLUTION_BLUE_SCALE_EXT,'params returns a single value, the scale factor to be applied to blue immediately after convolution.  See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_CONVOLUTION_COLOR_TABLE_SGI',GL_POST_CONVOLUTION_COLOR_TABLE_SGI,'params returns a single Boolean value indicating whether colors are passed through a lookup table before being processed by the color matrix operation.  See glColorTableSGI.'),
##	('GL_POST_CONVOLUTION_GREEN_BIAS_EXT',GL_POST_CONVOLUTION_GREEN_BIAS_EXT,'params returns a single value, the bias term to be added to green immediately after convolution. See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_CONVOLUTION_GREEN_SCALE_EXT',GL_POST_CONVOLUTION_GREEN_SCALE_EXT,'params returns a single value, the scale factor to be applied to green immediately after convolution.  See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_CONVOLUTION_RED_BIAS_EXT',GL_POST_CONVOLUTION_RED_BIAS_EXT,'params returns a single value, the bias term to be added to red immediately after convolution. See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_CONVOLUTION_RED_SCALE_EXT',GL_POST_CONVOLUTION_RED_SCALE_EXT,'params returns a single value, the scale factor to be applied to red immediately after convolution.  See glConvolutionFilter1DEXT, glConvolutionFilter2DEXT, and glSeparableFilter2DEXT.'),
##	('GL_POST_TEXTURE_FILTER_BIAS_RANGE_SGIX',GL_POST_TEXTURE_FILTER_BIAS_RANGE_SGIX,'params returns two values:  the minimum and maximum values for the texture bias factors. See glTexParameterfv and glTexParameteriv.'),
##	('GL_POST_TEXTURE_FILTER_SCALE_RANGE_SGIX',GL_POST_TEXTURE_FILTER_SCALE_RANGE_SGIX,'params returns two values:  the minimum and maximum values for the texture scale factors.'),
    ('GL_PROJECTION_STACK_DEPTH',GL_PROJECTION_STACK_DEPTH,'params returns one value, the number of matrices on the projection matrix stack.  See glPushMatrix.'),
    ('GL_READ_BUFFER',GL_READ_BUFFER,'params returns one value, a symbolic constant indicating which color buffer is selected for reading. See glReadPixels and glAccum.'),
    ('GL_RED_BIAS',GL_RED_BIAS,'params returns one value, the red bias factor used during pixel transfers.'),
    ('GL_RED_BITS',GL_RED_BITS,'params returns one value, the number of red bitplanes in each color buffer.'),
    ('GL_RED_SCALE',GL_RED_SCALE,'params returns one value, the red scale factor used during pixel transfers.  See glPixelTransfer.'),
##	('GL_REFERENCE_PLANE_EQUATION_SGIX',GL_REFERENCE_PLANE_EQUATION_SGIX,'params returns four values, the coefficients of the plane equation for the reference plane, expressed in clip coordinates.  See glReferencePlaneSGIX.'),
##	('GL_REFERENCE_PLANE_SGIX',GL_REFERENCE_PLANE_SGIX,'params returns a single Boolean value indicating whether depth values for pixel fragments are computed from the reference plane (true) or from the primitive being drawn (false).  See glReferencePlaneSGIX.'),
    ('GL_RENDER_MODE',GL_RENDER_MODE,'params returns one value, a symbolic constant indicating whether the GL is in render, select, or feedback mode.  See glRenderMode.'),
    ('GL_RGBA_MODE',GL_RGBA_MODE,'params returns a single Boolean value indicating whether the GL is in RGBA mode (true) or color index mode (false).  See glColor.'),
##	('GL_SAMPLE_ALPHA_TO_MASK_SGIS',GL_SAMPLE_ALPHA_TO_MASK_SGIS,'params returns a single Boolean value indicating whether fragment alpha values will modify the multisampling fragment mask.  See glSampleMaskSGIS.'),
##	('GL_SAMPLE_ALPHA_TO_ONE_SGIS',GL_SAMPLE_ALPHA_TO_ONE_SGIS,'params returns a single Boolean value indicating whether fragment alpha will be set to the maximum possible value after modifying the multisampling fragment mask.  See glSampleMaskSGIS.'),
##	('GL_SAMPLE_BUFFERS_SGIS',GL_SAMPLE_BUFFERS_SGIS,'params returns one value, the number of multisample buffers.'),
##	('GL_SAMPLE_MASK_INVERT_SGIS',GL_SAMPLE_MASK_INVERT_SGIS,'params returns a single Boolean value indicating whether the multisampling fragment modification mask is to be inverted.  See glSampleMaskSGIS.'),
##	('GL_SAMPLE_MASK_SGIS',GL_SAMPLE_MASK_SGIS,'params returns a single Boolean value indicating whether the multisampling fragment mask will be modified by a coverage mask.  See glSampleMaskSGIS.'),
##	('GL_SAMPLE_MASK_VALUE_SGIS',GL_SAMPLE_MASK_VALUE_SGIS,'params returns one value, the coverage of the multisampling fragment modification mask.  See glSampleMaskSGIS.'),
##	('GL_SAMPLE_PATTERN_SGIS',GL_SAMPLE_PATTERN_SGIS,'params returns one value, a symbolic constant indicating the multisampling pattern.  See glSamplePatternSGIS.'),
##	('GL_SAMPLES_SGIS',GL_SAMPLES_SGIS,'params returns one value, the number of samples per pixel used for multisampling.'),
    ('GL_SCISSOR_BOX',GL_SCISSOR_BOX,'params returns four values:  the x and y window coordinates of the scissor box, follow by its width and height.  See glScissor.'),
    ('GL_SCISSOR_TEST',GL_SCISSOR_TEST,'params returns a single Boolean value indicating whether scissoring is enabled.  See glScissor.'),
##	('GL_SEPARABLE_2D_EXT',GL_SEPARABLE_2D_EXT,'params returns a single Boolean value indicating whether separable two-dimensional convolution will be performed during pixel transfers.  See glSeparableFilter2DEXT.'),
    ('GL_SHADE_MODEL',GL_SHADE_MODEL,'params returns one value, a symbolic constant indicating whether the shading mode is flat or smooth.  See glShadeModel.'),
    ('GL_STENCIL_BITS',GL_STENCIL_BITS,'params returns one value, the number of bitplanes in the stencil buffer.'),
    ('GL_STENCIL_CLEAR_VALUE',GL_STENCIL_CLEAR_VALUE,'params returns one value, the index to which the stencil bitplanes are cleared.  See glClearStencil.'),
    ('GL_STENCIL_FAIL',GL_STENCIL_FAIL,'params returns one value, a symbolic constant indicating what action is taken when the stencil test fails.  See glStencilOp.'),
    ('GL_STENCIL_FUNC',GL_STENCIL_FUNC,'params returns one value, a symbolic constant indicating what function is used to compare the stencil reference value with the stencil buffer value.  See glStencilFunc.'),
    ('GL_STENCIL_PASS_DEPTH_FAIL',GL_STENCIL_PASS_DEPTH_FAIL,'params returns one value, a symbolic constant indicating what action is taken when the stencil test passes, but the depth test fails.  See glStencilOp.'),
    ('GL_STENCIL_PASS_DEPTH_PASS',GL_STENCIL_PASS_DEPTH_PASS,'params returns one value, a symbolic constant indicating what action is taken when the stencil test passes and the depth test passes.  See glStencilOp.'),
    ('GL_STENCIL_REF',GL_STENCIL_REF,'params returns one value, the reference value that is compared with the contents of the stencil buffer.  See glStencilFunc.'),
    ('GL_STENCIL_TEST',GL_STENCIL_TEST,'params returns a single Boolean value indicating whether stencil testing of fragments is enabled. See glStencilFunc and glStencilOp.'),
    ('GL_STENCIL_VALUE_MASK',GL_STENCIL_VALUE_MASK,'params returns one value, the mask that is used to mask both the stencil reference value and the stencil buffer value before they are compared. See glStencilFunc.'),
    ('GL_STENCIL_WRITEMASK',GL_STENCIL_WRITEMASK,'params returns one value, the mask that controls writing of the stencil bitplanes. glStencilMask.'),
    ('GL_STEREO',GL_STEREO,'params returns a single Boolean value indicating whether stereo buffers (left and right) are supported.'),
    ('GL_SUBPIXEL_BITS',GL_SUBPIXEL_BITS,'params returns one value, an estimate of the number of bits of subpixel resolution that are used to position rasterized geometry in window coordinates.'),
    ('GL_TEXTURE_1D',GL_TEXTURE_1D,'params returns a single Boolean value indicating whether 1D texture mapping is enabled.  See glTexImage1D.'),
##	('GL_TEXTURE_1D_BINDING_EXT',GL_TEXTURE_1D_BINDING_EXT,'params returns a single value, the name of the texture currently bound to the target GL_TEXTURE_1D.  See glBindTextureEXT.'),
    ('GL_TEXTURE_2D',GL_TEXTURE_2D,'params returns a single Boolean value indicating whether 2D texture mapping is enabled.  See glTexImage2D.'),
##	('GL_TEXTURE_2D_BINDING_EXT',GL_TEXTURE_2D_BINDING_EXT,'params returns a single value, the name of the texture currently bound to the target GL_TEXTURE_2D.  See glBindTextureEXT.'),
##	('GL_TEXTURE_3D_EXT',GL_TEXTURE_3D_EXT,'params returns a single Boolean value indicating whether 3D texture mapping is enabled.  See glTexImage3DEXT.'),
##	('GL_TEXTURE_3D_BINDING_EXT',GL_TEXTURE_3D_BINDING_EXT,'params returns a single value, the name of the texture currently bound to the target GL_TEXTURE_3D_EXT.  See glBindTextureEXT.'),
##	('GL_TEXTURE_COLOR_TABLE_SGI',GL_TEXTURE_COLOR_TABLE_SGI,'params returns a single Boolean value indicating whether texture colors are passed through a lookup table before being used to generate pixel fragments.  See glColorTableSGI.'),
    ('GL_TEXTURE_GEN_S',GL_TEXTURE_GEN_S,'params returns a single Boolean value indicating whether automatic generation of the S texture coordinate is enabled.  See glTexGen.'),
    ('GL_TEXTURE_GEN_T',GL_TEXTURE_GEN_T,'params returns a single Boolean value indicating whether automatic generation of the T texture coordinate is enabled.  See glTexGen.'),
    ('GL_TEXTURE_GEN_R',GL_TEXTURE_GEN_R,'params returns a single Boolean value indicating whether automatic generation of the R texture coordinate is enabled.  See glTexGen.'),
    ('GL_TEXTURE_GEN_Q',GL_TEXTURE_GEN_Q,'params returns a single Boolean value indicating whether automatic generation of the Q texture coordinate is enabled.  See glTexGen.'),
    ('GL_TEXTURE_STACK_DEPTH',GL_TEXTURE_STACK_DEPTH,'params returns one value, the number of matrices on the texture matrix stack.  See glPushMatrix.'),
    ('GL_UNPACK_ALIGNMENT',GL_UNPACK_ALIGNMENT,'params returns one value, the byte alignment used for reading pixel data from memory. See glPixelStore.'),
##	('GL_UNPACK_IMAGE_HEIGHT_EXT',GL_UNPACK_IMAGE_HEIGHT_EXT,'params returns one value, the image height used for reading (3D) pixel data from memory. See glPixelStore.'),
    ('GL_UNPACK_LSB_FIRST',GL_UNPACK_LSB_FIRST,'params returns a single Boolean value indicating whether single-bit pixels being read from memory are read first from the least significant bit of each unsigned byte.  See glPixelStore.'),
    ('GL_UNPACK_ROW_LENGTH',GL_UNPACK_ROW_LENGTH,'params returns one value, the row length used for reading pixel data from memory.  See glPixelStore.'),
    # following should be available, not marked as an extension item...
##	('GL_UNPACK_SKIP_IMAGES',GL_UNPACK_SKIP_IMAGES,'params returns one value, the number of images skipped before the first (3D) pixel is read from memory.  See glPixelStore.'),
##	('GL_UNPACK_SKIP_IMAGES_EXT',GL_UNPACK_SKIP_IMAGES_EXT,'params returns one value, the number of images skipped before the first (3D) pixel is read from memory.  See glPixelStore.'),
    ('GL_UNPACK_SKIP_PIXELS',GL_UNPACK_SKIP_PIXELS,'params returns one value, the number of pixel locations skipped before the first pixel is read from memory.  See glPixelStore.'),
    ('GL_UNPACK_SKIP_ROWS',GL_UNPACK_SKIP_ROWS,'params returns one value, the number of rows of pixel locations skipped before the first pixel is read from memory.  See glPixelStore.'),
    ('GL_UNPACK_SWAP_BYTES',GL_UNPACK_SWAP_BYTES,'params returns a single Boolean value indicating whether the bytes of two-byte and four-byte pixel indices and components are swapped after being read from memory.  See glPixelStore.'),
    ('GL_VIEWPORT',GL_VIEWPORT,'params returns four values:  the x and y window coordinates of the viewport, follow by its width and height.  See glViewport.'),
]
intarguments = [
    ('GL_BLUE_BITS',GL_BLUE_BITS,'params returns one value, the number of blue bitplanes in each color buffer.'),
    ('GL_CURRENT_INDEX',GL_CURRENT_INDEX,'params returns one value, the current color index.  See glIndex.'),
    ('GL_ACCUM_ALPHA_BITS',GL_ACCUM_ALPHA_BITS,'params returns one value, the number of alpha bitplanes in the accumulation buffer.'),
    ('GL_ACCUM_BLUE_BITS',GL_ACCUM_BLUE_BITS,'params returns one value, the number of blue bitplanes in the accumulation buffer.'),
    ('GL_ACCUM_CLEAR_VALUE',GL_ACCUM_CLEAR_VALUE,'params returns four values:  the red, green, blue, and alpha values used to clear the accumulation buffer.  Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glClearAccum.'),
    ('GL_ACCUM_GREEN_BITS',GL_ACCUM_GREEN_BITS,'params returns one value, the number of green bitplanes in the accumulation buffer.'),
    ('GL_ACCUM_RED_BITS',GL_ACCUM_RED_BITS,'params returns one value, the number of red bitplanes in the accumulation buffer.'),
    ('GL_ALPHA_BIAS',GL_ALPHA_BIAS,'params returns one value, the alpha bias factor used during pixel transfers.  See glPixelTransfer.'),
    ('GL_ALPHA_BITS',GL_ALPHA_BITS,'params returns one value, the number of alpha bitplanes in each color buffer.'),
    ('GL_ALPHA_SCALE',GL_ALPHA_SCALE,'params returns one value, the alpha scale factor used during pixel transfers.  See glPixelTransfer.'),
    ('GL_ALPHA_TEST',GL_ALPHA_TEST,'params returns a single Boolean value indicating whether alpha testing of fragments is enabled. See glAlphaFunc.'),
    ('GL_ALPHA_TEST_FUNC',GL_ALPHA_TEST_FUNC,'params returns one value, the symbolic name of the alpha test function. See glAlphaFunc.'),
    ('GL_ALPHA_TEST_REF',GL_ALPHA_TEST_REF,'params returns one value, the reference value for the alpha test.  See glAlphaFunc.  An integer value, if requested, is linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.'),
    ('GL_ATTRIB_STACK_DEPTH',GL_ATTRIB_STACK_DEPTH,'params returns one value, the depth of the attribute stack. If the stack is empty, zero is returned.  See glPushAttrib.'),
    ('GL_AUX_BUFFERS',GL_AUX_BUFFERS,'params returns one value, the number of auxiliary color buffers.'),
    ('GL_BLEND_DST',GL_BLEND_DST,'params returns one value, the symbolic constant identifying the destination blend function.  See glBlendFunc.'),
##	('GL_BLEND_EQUATION_EXT',GL_BLEND_EQUATION_EXT,'params returns one value, a symbolic constant identifying the blend equation.  See glBlendEquationEXT.'),
    ('GL_BLEND_SRC',GL_BLEND_SRC,'params returns one value, the symbolic constant identifying the source blend function.  See glBlendFunc.'),
##	('GL_BLEND_OP_SGI',GL_BLEND_OP_SGI,'params returns one value, the symbolic constant identifying the blend operator.  See glBlendFunc.'),
    ('GL_BLUE_BIAS',GL_BLUE_BIAS,'params returns one value, the blue bias factor used during pixel transfers.  See glPixelTransfer.'),
    ('GL_BLUE_SCALE',GL_BLUE_SCALE,'params returns one value, the blue scale factor used during pixel transfers.  See glPixelTransfer.'),
    ('GL_COLOR_MATERIAL_FACE',GL_COLOR_MATERIAL_FACE,'params returns one value, a symbolic constant indicating which materials have a parameter that is tracking the current color.  See glColorMaterial.'),
    ('GL_COLOR_MATERIAL_PARAMETER',GL_COLOR_MATERIAL_PARAMETER,'params returns one value, a symbolic constant indicating which material parameters are tracking the current color.  See glColorMaterial.'),
##	('GL_COLOR_MATRIX_STACK_DEPTH_SGI',GL_COLOR_MATRIX_STACK_DEPTH_SGI,'params returns one value, the maximum supported depth of the color matrix stack. See glPushMatrix, glPixelTransfer.'),
    ('GL_CULL_FACE_MODE',GL_CULL_FACE_MODE,'params returns one value, a symbolic constant indicating which polygon faces are to be culled. See glCullFace.'),
    ('GL_DEPTH_CLEAR_VALUE',GL_DEPTH_CLEAR_VALUE,'params returns one value, the value that is used to clear the depth buffer.  Integer values, if requested, are linearly mapped from the internal floating-point representation such that 1.0 returns the most positive representable integer value, and -1.0 returns the most negative representable integer value.  See glClearDepth.'),
    ('GL_CURRENT_RASTER_INDEX',GL_CURRENT_RASTER_INDEX,'params returns one value, the color index of the current raster position. See glRasterPos.'),
    ('GL_DEPTH_BITS',GL_DEPTH_BITS,'params returns one value, the number of bitplanes in the depth buffer.'),
    ('GL_DEPTH_FUNC',GL_DEPTH_FUNC,'params returns one value, the symbolic constant that indicates the depth comparison function. See glDepthFunc.'),
]

stringarguments = [
    ('GL_VENDOR', GL_VENDOR, '''Returns the company responsible for this GL implementation.  This name does not change from release to release.  For	Silicon Graphics the string is "SGI".'''),
    ('GL_RENDERER', GL_RENDERER, '''Returns the name of the renderer.	This name is typically specific to a particular configuration of a hardware platform. It	does not change	from release to	release.  The renderer strings for Silicon Graphics graphic engines are listed in	the MACHINE DEPENDENCIES section below.'''),
    ('GL_VERSION', GL_VERSION, '''Returns a version or release number.  For SGI releases prior to Irix 5.3 the string is "1.0".  For	Irix 5.3 and subsequent releases the format is GL version> Irix	 patch ";	for example in	the Irix 5.3 release the string	is "1.0	Irix 5.3".'''),
##	('GL_EXTENSIONS', GL_EXTENSIONS, '''Returns a space-separated list of supported extensions to GL.'''),
]
     	
if __name__ == "__main__":
    TestContext.ContextMainLoop()