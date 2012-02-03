"""Shader node implementation"""
from OpenGL.GL import *
from OpenGL.GL import shaders as GL_shaders
from OpenGL.GLU import *
from OpenGL.GLUT import *
from OpenGL import error
from OpenGL.arrays import vbo
from OpenGLContext.arrays import array,reshape
from OpenGLContext import context
from vrml.vrml97 import shaders
import operator
from vrml import field,node,fieldtypes,protofunctions
from OpenGLContext.scenegraph import polygonsort,boundingvolume
from OpenGLContext.arrays import array
LOCAL_ORIGIN = array( [[0,0,0,1.0]], 'f')

import time, sys
from OpenGL.extensions import alternate
import logging
log = logging.getLogger( __name__ )


class _Buffer( object ):
    """VBO based buffer implementation for generic geometry"""
    GL_USAGE_MAPPING = {
        'STREAM_DRAW': GL_STREAM_DRAW,
        'STREAM_READ': GL_STREAM_READ,
        'STREAM_COPY': GL_STREAM_COPY,
        'STATIC_DRAW': GL_STATIC_DRAW,
        'STATIC_READ': GL_STATIC_READ,
        'STATIC_COPY': GL_STATIC_COPY,
        'DYNAMIC_DRAW': GL_DYNAMIC_DRAW,
        'DYNAMIC_READ': GL_DYNAMIC_READ,
        'DYNAMIC_COPY': GL_DYNAMIC_COPY,
    }
    GL_TYPE_MAPPING = {
        'ARRAY': GL_ARRAY_BUFFER,
        'ELEMENT': GL_ELEMENT_ARRAY_BUFFER,
        'UNIFORM': GL_UNIFORM_BUFFER,
        'TEXTURE': GL_TEXTURE_BUFFER,
        'TRANSFORM_FEEDBACK': GL_TRANSFORM_FEEDBACK_BUFFER,
    }
    def gl_usage( self ):
        return self.GL_USAGE_MAPPING[ self.usage ]
    def gl_target( self ):
        return self.GL_TYPE_MAPPING[ self.type ]
    def vbo( self, mode ):
        """Render this buffer on the mode"""
        uploaded = mode.cache.getData( self, 'buffer' )
        if uploaded is None:
            uploaded = vbo.VBO( 
                self.buffer, 
                usage=self.gl_usage(), 
                target=self.gl_target(),
            ) # TODO: stream type
            holder = mode.cache.holder( self, uploaded, 'buffer' )
            holder.depend( self, 'buffer' )
        return uploaded
    def bind( self, mode ):
        """Bind this buffer so that we can perform e.g. mappings on it"""
        vbo = self.vbo(mode)
        vbo.bind()
        return vbo
    def unbind( self, mode ):
        """Unbind the vbo"""
        vbo = self.vbo(mode)
        vbo.unbind()
        return vbo
    
class ShaderBuffer( _Buffer, shaders.ShaderBuffer ):
    """Regular vertex-buffer mechanism"""
class ShaderIndexBuffer( _Buffer, shaders.ShaderIndexBuffer ):
    """Index array buffer mechanism"""
    
class ShaderAttribute( shaders.ShaderAttribute ):
    """VBO-based buffer implementation for generic geomtry indices"""
    def render( self, shader, mode ):
        """Set this uniform value for the given shader
        
        This is called at render-time to update the value...
        """
        location = shader.getLocation( mode, self.name, uniform=False )
        if location is not None and location != -1:
            vbo = self.buffer.bind( mode )
            glVertexAttribPointer( 
                location, self.size, GL_FLOAT, False, self.stride, 
                vbo+self.offset
            )
            glEnableVertexAttribArray( location )
            return (vbo,location)
        return None
    def renderPost( self, mode, shader, token=None ):
        if token:
            vbo,location = token 
            vbo.unbind()
            glDisableVertexAttribArray( location )
    
    def bufferView( self ):
        """Retrieve a view of our buffer that is just this attribute's values"""
        if not self.buffer:
            raise AttributeError( 'No buffer currently' )
        buffer = self.buffer.buffer
        # okay, now slice-and-dice it...
        # TODO: watch for cases where the buffer is something 
        # other than the native-size?  Shouldn't be possible given 
        # the typed nature of the buffer property.
        shape = buffer.shape
        offset = self.offset//buffer.itemsize
        stride = self.stride//buffer.itemsize
        # okay, are we a multi-dimensional buffer?
        if len(shape) == 2:
            if stride%shape[-1]:
                # is not evenly divisble...
                raise ValueError( 
                    """Stride %s is not evenly divisible into matrix shape %s"""%(
                        stride, shape
                    ) 
                )
            else:
                step = stride//shape[-1]
            # TODO: support higher-order shapes
            if step > 1:
                return buffer[::step,offset:offset+self.size]
            else:
                return buffer[:,offset:offset+self.size]
        elif len(shape) == 1:
            # we're a ravelled array...
            buffer = reshape( buffer, (-1,stride))
            return buffer[:,offset:offset+self.size]
        else:
            raise NotImplemented( 
                """Haven't implemented view support for N dimensional arrays"""
            )
    def boundingVolume( self, mode ):
        """Calculate bounding volume of this attribute's current values"""
        current = boundingvolume.getCachedVolume( self )
        if current:
            return current 
        try:
            buffer = self.bufferView()
        except AttributeError, err:
            bv = boundingvolume.BoundingVolume()
        else:
            bv = boundingvolume.AABoundingBox.fromPoints( buffer )
            print 'buffer points', buffer
        return boundingvolume.cacheVolume( 
            self, bv, (
                (self,None),
                (self,'buffer'),
                (self,'offset'),
                (self,'stride'),
                (self.buffer,'buffer'),
            ),
        )

class _Uniform( object ):
    """Uniform common operations"""
    warned = False

class FloatUniform( _Uniform, shaders.FloatUniform ):
    """Uniform (variable) binding for a shader"""
    def render( self, shader, mode ):
        """Set this uniform value for the given shader
        
        This is called at render-time to update the value...
        """
        location = shader.getLocation( mode, self.name, uniform=True )
        if location is not None and location != -1:
            value = self.value
            shape = value.shape 
            shape_length = len(self.shape)
            assert shape[-shape_length:] == self.shape,(shape,self.shape, value)
            if shape[:-shape_length]:
                size = reduce( operator.mul, shape[:-shape_length] )
            else:
                size = 1
            return self.baseFunction( location, size, value )
        return None
class IntUniform( _Uniform, shaders.IntUniform ):
    """Uniform (variable) binding for a shader (integer form)
    """

class _TextureUniform( _Uniform ):
    def bind( self, shader, mode, index ):
        location = shader.getLocation( mode, self.name, uniform=True )
        if location is not None and location != -1:
            if self.value:
                self.baseFunction( location, index )
                return True 
        return False
    
class TextureUniform( _TextureUniform, shaders.TextureUniform ):
    """Uniform (variable) binding for a texture sampler"""
    baseFunction = staticmethod( glUniform1i )
    def render( self, shader, mode, index ):
        """Bind the actual uniform value"""
        location = shader.getLocation( mode, self.name, uniform=True )
        if location is not None and location != -1:
            if self.value:
                self.baseFunction( location, index )
                glActiveTexture( GL_TEXTURE0 + index )
                self.value.render( mode.visible, mode.lighting, mode )
                return True 
        return False
class TextureBufferUniform( _TextureUniform, shaders.TextureBufferUniform ):
    """Uniform (variable) finding for a VBO-based texture sampler"""
    baseFunction = staticmethod( glUniform1i )
    def get_format( self ):
        return globals().get( 'GL_%s'%( self.format ) )
    def texture( self, mode ):
        """Render this buffer on the mode"""
        texture = mode.cache.getData( self, 'texture' )
        if texture is None:
            texture = glGenTextures( 1 )
            holder = mode.cache.holder( self, texture, 'texture' )
        return texture
    def render( self, shader, mode, index ):
        """Bind the actual uniform value"""
        location = shader.getLocation( mode, self.name, uniform=True )
        if location is not None and location != -1:
            if self.value:
                self.baseFunction( location, index )
                glActiveTexture( GL_TEXTURE0 + index )
                glBindTexture( GL_TEXTURE_BUFFER, self.texture( mode ) )
                vbo = self.value.vbo(mode)
                vbo.bind()
                try:
                    glTexBuffer( GL_TEXTURE_BUFFER, self.get_format(), int(vbo) )
                finally:
                    vbo.unbind()
                return True 
        return False
    

def _uniformCls( suffix ):
    def buildCls( name, suffix, size, function, base ):
        cls = type( name, (base,), {
            'suffix': suffix,
            'PROTO': name,
            'baseFunction': function,
            'shape': size,
        } )
        globals()[name] = cls 
    
    function_name = 'glUniform'
    if suffix.startswith( 'm' ):
        size = suffix[1:]
        function_name = 'glUniformMatrix%sfv'%( size, )
        function = globals()[function_name] 
        size = map( int, size.split('x' ))
        if len(size) == 1:
            size = [size[0],size[0]]
        size = tuple(size)
        name = 'FloatUniform'+suffix
        buildCls( name, suffix, size, function, FloatUniform )
    else:
        if suffix.endswith( 'i' ):
            base = IntUniform
            name = 'IntUniform'+suffix
        else:
            base = FloatUniform
            name = 'FloatUniform'+suffix
        function_name = 'glUniform%sv'%( suffix, )
        function = globals()[function_name] 
        size = (int(suffix[:1]), )
        buildCls( name, suffix, size, function, base )

FLOAT_UNIFORM_SUFFIXES = ('1f','2f','3f','4f','m2','m3','m4','m2x3','m3x2','m2x4','m4x2','m3x4','m4x3')
INT_UNIFORM_SUFFIXES = ('1i','2i','3i','4i')
for suffix in FLOAT_UNIFORM_SUFFIXES + INT_UNIFORM_SUFFIXES:
    _uniformCls( suffix )


class ShaderURLField( fieldtypes.MFString ):
    """Field for managing interactions with a Shader's URL value"""
    fieldType = "MFString"
    def fset( self, client, value, notify=1 ):
        """Set the client's URL, then try to load the image"""
        value = super(ShaderURLField, self).fset( client, value, notify )
        if value:
            import threading
            threading.Thread(
                name = "Background load of %s"%(value),
                target = self.loadBackground,
                args = ( client, value, context.Context.allContexts,),
            ).start()
        return value
    def loadBackground( self, client, url, contexts ):
        overall = [None]* len(url)
        threads = []
        for i,value in enumerate(url):
            import threading
            t = threading.Thread(
                name = "Background load of %s"%(value),
                target = self.subLoad,
                args = ( client, value, i, overall),
            )
            t.start()
            threads.append( t )
        for t in threads:
            t.join()
        result = [ x for x in overall if x is not None ]
        if len(result) == len(overall):
            client.source = '\n'.join( result )
            # TODO: make this an observation that causes the 
            # contexts to redraw, *not* something the node does 
            # explicitly...
            for context in contexts:
                c = context()
                if c:
                    c.triggerRedraw(1)
            return
    def subLoad( self, client, urlFragment, i, overall ):
        from OpenGLContext.loaders.loader import Loader
        try:
            baseNode = protofunctions.root(client)
            if baseNode:
                baseURI = baseNode.baseURI
            else:
                baseURI = None
            result = Loader( urlFragment, baseURL = baseURI )
        except IOError:
            pass
        else:
            if result:
                baseURL, filename, file, headers = result
                overall[i] = file.read()
                return True
        # should set client.image to something here to indicate
        # failure to the user.
        log.warn( """Unable to load any shader from the url %s for the node %s""", urlFragment, str(client))

class GLSLImport( shaders.GLSLImport ):
    """GLSL-based importable code library"""
    url = ShaderURLField( 'url', 'MFString', list)

class GLSLShader( shaders.GLSLShader ):
    """GLSL-based shader node"""
    url = ShaderURLField( 'url', 'MFString', list)
    compileLog = field.newField( ' compileLog', 'SFString', '' )
    def holderDepend( self, holder ):
        holder.depend( self,  'source')
        holder.depend( self,  'type')
    def compile(self):
        if not self.source:
            return False
        source = []
        for import_lib in self.imports:
            if not import_lib.source:
                return False 
            source.extend( import_lib.source )
        source.extend( self.source )
        try:
            if self.type == 'VERTEX':
                shader = GL_shaders.compileShader(
                    source, 
                    GL_VERTEX_SHADER
                )
            elif self.type == 'FRAGMENT':
                shader = GL_shaders.compileShader(
                    source, GL_FRAGMENT_SHADER
                )
            else:
                log.error(
                    'Unknown shader type: %s in %s', 
                    self.type, 
                    self, 
                )
                return None
        except RuntimeError, err:
            self.compileLog = err.args[0]
            return None
        return shader
    def visible( self, *args, **named ):
        return True 

class _GLSLObjectCache( object ):
    shader = None 
    locationMap = None

class GLSLObject( shaders.GLSLObject ):
    """GLSL-based shader object (compiled set of shaders)"""
    IMPLEMENTATION = 'GLSL'
    compileLog = field.newField( ' compileLog', 'SFString', '' )
    def render( self, mode ):
        """Render this shader in the current mode"""
        renderer = mode.cache.getData(self)
        if renderer is None:
            renderer = self.compile( mode )
            if renderer is False:
                log.warn("""%s""",
                    self.compileLog,
                )
        if renderer not in (None,False):
            try:
                GL_shaders.glUseProgram( renderer )
            except error.GLError, err:
                log.error( '''Failure compiling: %s''', '\n'.join([
                    '%s: %s'%(shader.url or shader.source,shader.compileLog)
                    for shader in self.shaders
                ]))
                raise
            else:
                for uniform in self.uniforms:
                    uniform.render( self, mode )
                # TODO: retrieve maximum texture count and restrict to that...
                i = 0
                for texture in self.textures:
                    if texture.render( self, mode, i ):
                        i += 1
        return True,True,True,renderer 
    def holderDepend( self, holder ):
        """Make this holder depend on our compilation vars"""
        for shader in self.shaders:
            # TODO: cache links...
            shader.holderDepend( holder )
        holder.depend( self,  'shaders' )
        return holder
    def compile(self, mode):
        """Compile into GLSL linked object"""
        holder = self.holderDepend( mode.cache.holder(self,None) )
        program = glCreateProgram()
        holder.data = program
        subShaders = []
        for shader in self.shaders:
            # TODO: cache links...
            subShader = shader.compile()
            if subShader:
                glAttachShader(program, subShader )
                subShaders.append( subShader )
            elif shader.source:
                log.info( 'Failure compiling: %s %s', shader.compileLog, shader.url or shader.source )
        if len(subShaders) == len(self.shaders):
            glLinkProgram(program)
            glUseProgram( program )
            # TODO: retrieve maximum texture count and restrict to that...
            i = 0
            for texture in self.textures:
                if texture.bind( self, mode, i ):
                    i += 1
            
            glValidateProgram( program )
            validation = glGetProgramiv( program, GL_VALIDATE_STATUS )
            if validation == GL_FALSE:
                self.compileLog += """Validation failure (%s): %s"""%(
                    validation,
                    glGetProgramInfoLog( program ),
                )
                program = False 
            else:
                link_status = glGetProgramiv( program, GL_LINK_STATUS )
                if link_status == GL_FALSE:
                    self.compileLog += """Link failure (%s): %s"""%(
                        link_status,
                        glGetProgramInfoLog( program ),
                    )
                    program = False
            for subShader in subShaders:
                glDeleteShader( subShader )
            holder.data = program
            return program
        else:
            log.debug( 'Not done loading shader source yet' )
        holder.data = 0
        return None
    def program( self, mode ):
        """Retrieve our program ID"""
        renderer = mode.cache.getData( self )
        if renderer is None:
            renderer = self.compile( mode )
        return renderer
    def renderPost( self, token, mode ):
        """Post-render cleanup..."""
        if token:
            glUseProgram( 0 )
            # TODO: unbind our attributes...
    def getVariable( self, name ):
        """Retrieve uniform/attribute by name"""
        for uniform in self.uniforms:
            if uniform.name == name:
                return uniform 
        return None
    def getLocation( self, mode, name, uniform=True ):
        """Retrieve attribute/uniform location"""
        locationMap = mode.cache.getData( self, 'locationMap' )
        if locationMap is None:
            locationMap = {}
            holder = mode.cache.holder( self, locationMap, 'locationMap' )
            holder = self.holderDepend( 
                mode.cache.holder(self,locationMap,'locationMap') 
            )
        try:
            return locationMap[ name ]
        except KeyError, err:
            program = self.program(mode)
            if uniform:
                location = glGetUniformLocation( program, name )
            else:
                location = glGetAttribLocation( program, name )
            locationMap[ name ] = location 
            if location == -1:
                log.warn( 'Unable to resolve uniform name %s', name )
            return location 
    def sortKey( self, mode, matrix ):
        """Produce the sorting key for this shape's appearance/shaders/etc"""
        # TODO: figure out how to handle 
        return False,[],None
        
class Shader( shaders.Shader ):
    """Shader is a programmable substitute for an Appearance node"""
    current = field.newField( ' current','SFNode',1, node.NULL )
    uniformIDs = None
    attributeIDs = None
    def render (self, mode=None):
        """Render the shader"""
        current = self.currentImplementation()
        if current:
            return current.render( mode )
        else:
            return True,True,True,None
    def currentImplementation( self ):
        current = self.current
        if not current:
            for object in self.objects:
                if object.IMPLEMENTATION == 'GLSL':
                    self.current = current = object 
        return self.current
        
    def renderPost( self, textureToken=None, mode=None ):
        """Cleanup after rendering of this node has completed"""
        if self.current:
            return self.current.renderPost( textureToken, mode )
    def sortKey( self, mode, matrix ):
        """Produce the sorting key for this shape's appearance/shaders/etc"""
        current = self.currentImplementation()
        if current:
            return current.sortKey( mode, matrix )
        else:
            return (False,[],None)

class ShaderGeometry( shaders.ShaderGeometry ):
    """Renderable geometry type using shaders"""
    def Render (self, mode = None):
        """Do run-time rendering of the Shape for the given mode"""
        if not self.attributes or not self.appearance:
            return None 
        _,_,_,token = self.appearance.render( mode )
        if token is not None:
            try:
                current = self.appearance.current
                if not current:
                    return False
                tokens = []
                for attribute in self.attributes:
                    sub_token = attribute.render( current, mode )
                    tokens.append( (attribute,sub_token) )
                try:
                    if self.uniforms:
                        for uniform in self.uniforms:
                            uniform.render( current, mode )
                    if self.slices:
                        # now iterate over our slices...
                        for slice in self.slices:
                            for uniform in slice.uniforms:
                                uniform.render( current, mode )
                            glDrawArrays( 
                                GL_TRIANGLES, slice.offset, slice.count 
                            )
                    else:
                        # TODO: don't currently have a good way to get 
                        # the proper dimension for the arrays...
                        pass 
                finally:
                    for attribute,token in tokens:
                        attribute.renderPost( mode,token )
            finally:
                self.appearance.renderPost( token, mode )
                glBindBuffer( GL_ARRAY_BUFFER,0 )
    def sortKey( self, mode, matrix ):
        """Produce the sorting key for this shape's appearance/shaders/etc"""
        # distance calculation...
        distance = polygonsort.distances(
            LOCAL_ORIGIN,
            modelView = matrix,
            projection = mode.getProjection(),
            viewport = mode.getViewport(),
        )[0]
        if self.appearance:
            key = self.appearance.sortKey( mode, matrix )
        else:
            key = (False,[],None)
        if key[0]:
            distance = -distance
        return key[0:2]+ (distance,) + key[1:]
    
    def boundingVolume( self, mode ):
        """Create a bounding-volume object for this node

        This is our geometry's boundingVolume, with the
        addition that any dependent volume must be dependent
        on our geometry field.
        """
        bb = None
        for attrib in self.attributes:
            if attrib.isCoord:
                bv = attrib.boundingVolume( mode )
                if bv and bb:
                    bb = boundingvolume.AABoundingBox.union( (bb,bv))
                elif bv:
                    bb = bv 
        if not bb:
            # can't determine bounding box, so have to go with the 
            # always-visible version...
            return boundingvolume.UnboundedVolume()
        return bb
    def visible( self, frustum=None, matrix=None, occlusion=0, mode=None ):
        """Check whether this renderable node intersects frustum

        frustum -- the bounding volume frustum with a planes
            attribute which defines the plane equations for
            each active clipping plane
        matrix -- the active OpenGL transformation matrix for
            this node, used to determine the transforms for
            the grouping-node's bounding volumes.  Is calculated
            from current OpenGL state if not provided.
        """
        try:
            return self.boundingVolume(mode).visible( 
                frustum, matrix, occlusion=occlusion, mode=mode 
            )
        except Exception, err:
            tb = traceback.format_exc( )
            log.warn(
                """Failure during Shape.visible check for %r:\n%s""",
                self,
                tb
            )

class ShaderSlice( shaders.ShaderSlice ):
    """Slice of a shader to render"""
    

