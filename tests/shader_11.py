#! /usr/bin/env python
'''=Use Declarative Structures=

[shader_11.py-screen-0001.png Screenshot]

This tutorial:

    * configure our light array from VRML97 scenegraph objects
    * configure our material structure from VRML97 scenegraph objects
    * add simple texturing

The purpose of this tutorial is to consolidate our work so far 
so that we can reuse it in further tutorials without needing to 
repeat code all the time.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL.shaders import *
'''We're going to use VRML97 nodes to configure our shaders,
so we'll import the whole set of VRML97 base nodes (and the 
OpenGLContext extended nodes as well, though we aren't going 
to use them here).'''
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
    """Demonstrates use of attribute types in GLSL
    """
    '''Rather than declaring our constants as context attributes, we'll 
    make an explicit namespace in which the constants are stored.'''
    shader_constants = dict(
        LIGHT_COUNT = 5,
        LIGHT_SIZE = 7,
        
        AMBIENT = 0,
        DIFFUSE = 1,
        SPECULAR = 2,
        POSITION = 3,
        ATTENUATION = 4,
        # SPOT_PARAMS [ cos_spot_cutoff, spot_exponent, ignored, is_spot ]
        SPOT_PARAMS = 5,
        SPOT_DIR = 6,
    )
    def createLights( self ):
        return [
            DirectionalLight(
                color = (.1,1,.1),
                intensity = 1.0,
                ambientIntensity = 0.1,
                direction = (-8,-20,-8),
            ),
            SpotLight(
                location = (-2.5,2.5,2.5),
                color = (1,.05,.05),
                ambientIntensity = .1,
                direction = (2.5,-5.5,-2.5),
            ),
            PointLight(
                location = (0,-3.06,3.06),
                color = (.05,.05,1),
                ambientIntensity = .1,
            ),
        ]
    
    def OnInit( self ):
        """Initialize the context"""
        '''Our first step in making the shader-based code more flexible is 
        to make the number and type of lights depend on a declared set of 
        light "nodes" rather than explicitly creating arrays of lighting 
        parameters.  The flexibility this provides means that we can easily 
        demo all 3 types of supported lights here.'''
        self.lights = self.createLights()
        '''Now we take the set of lights and turn them into an array of 
        lighting parameters to be passed into the shader.'''
        self.LIGHTS = array([
            self.lightAsArray(l)
            for l in self.lights 
        ],'f')
        '''Instead of the hard-coded lighting count, we update the light 
        count before compiling the shader.  In the real world we'd want to 
        make the number of lights a parameter per-object so that we could 
        generate a light-count-specific shader shared among all objects 
        with the same light-count.
        '''
        self.shader_constants['LIGHT_COUNT'] = len(self.lights)
        
        '''Load our shader functions that we've stored in resources and files.'''
        from OpenGLContext.resources.phongprecalc_vert import data as phong_preCalc
        from OpenGLContext.resources.phongweights_frag import data as phong_weightCalc
        light_preCalc = open( '_shader_tut_lightprecalc.vert' ).read()
        
        lightConst = "\n".join([
            "const int %s = %s;"%( k,v )
            for k,v in self.shader_constants.items()
        ]) + """
        uniform vec4 lights[ LIGHT_COUNT*LIGHT_SIZE ];
        
        varying vec3 EC_Light_half[LIGHT_COUNT];
        varying vec3 EC_Light_location[LIGHT_COUNT]; 
        varying float Light_distance[LIGHT_COUNT]; 
        
        varying vec3 baseNormal;
        varying vec2 Vertex_texture_coordinate_var;
        """
        
        vertex = compileShader( 
            lightConst + phong_preCalc + light_preCalc +
        """
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;
        attribute vec2 Vertex_texture_coordinate;
        void main() {
            gl_Position = gl_ModelViewProjectionMatrix * vec4( 
                Vertex_position, 1.0
            );
            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
            light_preCalc(Vertex_position);
            Vertex_texture_coordinate_var = Vertex_texture_coordinate;
        }""", GL_VERTEX_SHADER)
        
        fragment = compileShader( 
            lightConst + phong_weightCalc + """
        struct Material {
            vec4 ambient;
            vec4 diffuse;
            vec4 specular;
            float shininess;
        };
        uniform Material material;
        uniform vec4 Global_ambient;
        uniform sampler2D diffuse_texture;
        
        void main() {
            vec4 fragColor = Global_ambient * material.ambient;
            
            vec4 texDiffuse = texture2D( 
                diffuse_texture, Vertex_texture_coordinate_var 
            );
            texDiffuse = mix( material.diffuse, texDiffuse, .5 );
            
            // Again, we've moved the "hairy" code into the reusable 
            // function, our loop simply calls the phong calculation 
            // with the values from our uniforms and attributes...
            int i,j;
            for (i=0;i<LIGHT_COUNT;i++) {
                j = i * LIGHT_SIZE;
                vec3 weights = phong_weightCalc(
                    normalize(EC_Light_location[i]),
                    normalize(EC_Light_half[i]),
                    normalize(baseNormal),
                    material.shininess,
                    Light_distance[i],
                    lights[j+ATTENUATION],
                    lights[j+SPOT_PARAMS],
                    lights[j+SPOT_DIR]
                );
                fragColor = (
                    fragColor 
                    + (lights[j+AMBIENT] * material.ambient * weights.x)
                    + (lights[j+DIFFUSE] * texDiffuse * weights.y)
                    + (lights[j+SPECULAR] * material.specular * weights.z)
                );
            }
            gl_FragColor = fragColor;
        }
        """, GL_FRAGMENT_SHADER)
        self.shader = compileProgram(vertex,fragment)
        self.coords,self.indices,self.count = Sphere( 
            radius = 1 
        ).compile()
        
        self.appearance = Appearance( 
            material = Material(
                diffuseColor = (1,1,1),
                ambientIntensity = .1,
                shininess = .5,
            ),
            texture = ImageTexture(
                url = ['marbleface.jpeg'],
            ),
        )
        
        self.uniform_locations = {}
        for uniform,value in self.UNIFORM_VALUES:
            self.findUniform( self.shader, uniform )
        self.findUniform( self.shader, 'lights' )
        for uniform in self.MATERIAL_UNIFORMS:
            self.findUniform( self.shader, uniform )
        
        for attribute in (
            'Vertex_position','Vertex_normal','Vertex_texture_coordinate',
        ):
            location = glGetAttribLocation( self.shader, attribute )
            if location in (None,-1):
                print 'Warning, no attribute: %s'%( uniform )
            setattr( self, attribute+ '_loc', location )
    UNIFORM_VALUES = [
        ('Global_ambient',(.05,.05,.05,1.0)),
    ]
    def findUniform( self, shader, uniform ):
        location = glGetUniformLocation( shader, uniform )
        if location in (None,-1):
            print 'Warning, no uniform: %s'%( uniform )
        self.uniform_locations[uniform] = location
        return location
        
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        for i,light in enumerate( self.lights ):
            # update in case there's a change...
            self.LIGHTS[i] = self.lightAsArray( light )
        glActiveTexture( GL_TEXTURE0 + 1 )
        try:
            self.appearance.texture.render( mode.visible, mode.lighting, mode )
        finally:
            pass
            glActiveTexture( GL_TEXTURE0 )
        
        glUseProgram(self.shader)
        glUniform1i( self.uniform_locations['diffuse_texture'], 1 )
        try:
            self.coords.bind()
            self.indices.bind()
            stride = self.coords.data[0].nbytes
            try:
                count = self.shader_constants['LIGHT_COUNT'] * self.shader_constants['LIGHT_SIZE']
                glUniform4fv( 
                    self.uniform_locations['lights'],
                    count,
                    self.LIGHTS
                )
                for key,value in self.materialFromAppearance( 
                    self.appearance, mode 
                ).items():
                    loc = self.uniform_locations.get( key )
                    if isinstance( value, float ):
                        glUniform1f( loc, value )
                    else:
                        glUniform4fv( loc, 1, value )
                for uniform,value in self.UNIFORM_VALUES:
                    location = self.uniform_locations.get( uniform )
                    if location not in (None,-1):
                        if len(value) == 4:
                            glUniform4f( location, *value )
                        elif len(value) == 3:
                            glUniform3f( location, *value )
                        elif len(value) == 1:
                            glUniform1f( location, *value )
                glEnableVertexAttribArray( self.Vertex_position_loc )
                glEnableVertexAttribArray( self.Vertex_normal_loc )
                glEnableVertexAttribArray( self.Vertex_texture_coordinate_loc )
                glVertexAttribPointer( 
                    self.Vertex_position_loc, 
                    3, GL_FLOAT,False, stride, self.coords
                )
                glVertexAttribPointer( 
                    self.Vertex_texture_coordinate_loc, 
                    2, GL_FLOAT,False, stride, self.coords+(3*4)
                )
                glVertexAttribPointer( 
                    self.Vertex_normal_loc, 
                    3, GL_FLOAT,False, stride, self.coords+(5*4)
                )
                glDrawElements(
                    GL_TRIANGLES, self.count,
                    GL_UNSIGNED_SHORT, self.indices
                )
            finally:
                self.coords.unbind()
                self.indices.unbind()
                glDisableVertexAttribArray( self.Vertex_position_loc )
                glDisableVertexAttribArray( self.Vertex_normal_loc )
                glDisableVertexAttribArray( self.Vertex_texture_coordinate_loc )
        finally:
            glUseProgram( 0 )
    
    def lightAsArray( self, light ):
        """Given a single VRML97 light-node, produce light value array"""
        def sk(k):
            return self.shader_constants[k]
        key = 'uniform-array'
        result = self.cache.getData(light, key= key )
        if result is None:
            result = zeros( (sk('LIGHT_SIZE'),4), 'f' )
            depends_on = ['on']
            if light.on:
                color = light.color
                depends_on.append( 'color' )
                D,A,S,P,AT = (
                    sk('DIFFUSE'),
                    sk('AMBIENT'),
                    sk('SPECULAR'),
                    sk('POSITION'),
                    sk('ATTENUATION')
                )
                result[ D ][:3] = color * light.intensity
                result[ D ][3] = 1.0
                result[ A ][:3] = color * light.ambientIntensity
                result[ A ][3] = 1.0
                result[ S ][:3] = color
                result[ S ][3] = 1.0
                depends_on.append( 'intensity' )
                depends_on.append( 'ambientIntensity' )
                
                if not isinstance( light, DirectionalLight ):
                    result[P][:3] = light.location
                    result[P][3] = 1.0
                    result[AT][:3] = light.attenuation
                    result[AT][3] = 1.0
                    depends_on.append( 'location' )
                    depends_on.append( 'attenuation' )
                    if isinstance( light, SpotLight ):
                        result[sk('SPOT_DIR')][:3] = light.direction 
                        result[sk('SPOT_DIR')][3] = 1.0
                        result[sk('SPOT_PARAMS')] = [
                            cos( light.beamWidth/4.0 ),
                            light.cutOffAngle/light.beamWidth,
                            0,
                            1.0,
                        ]
                        depends_on.append( 'direction' )
                        depends_on.append( 'cutOffAngle' )
                        depends_on.append( 'beamWidth' )
                else:
                    result[P][:3] = -light.direction
                    result[P][3] = 0.0
                    depends_on.append( 'direction' )
            holder = self.cache.holder( 
                light,result,key=key
            )
            for field in depends_on:
                holder.depend( light, field )
        return result 
    MATERIAL_UNIFORMS = [
        'material.shininess',
        'material.ambient',
        'material.diffuse',
        'material.specular',
        'diffuse_texture',
    ]
    def materialFromAppearance( self, appearance, mode ):
        """Convert VRML97 appearance node to series of uniform calls"""
        material = appearance.material 
        key = 'uniform-array'
        data = self.cache.getData(material, key= key )
        if data is None:
            color = material.diffuseColor 
            ambient = material.ambientIntensity * color 
            shininess = material.shininess
            specular = material.specularColor
            alpha = 1.0 - material.transparency
            def as4( v ):
                x,y,z = v 
                return (x,y,z,alpha)
            data = (shininess,as4(ambient),as4(color),as4(specular))
            holder = self.cache.holder( 
                material,data,key=key
            )
            for field in [
                'diffuseColor','ambientIntensity',
                'shininess','specularColor','transparency'
            ]:
                holder.depend( material, field )
        shininess,ambient,color,specular = data
        return {
            'material.shininess': shininess,
            'material.ambient': ambient,
            'material.diffuse': color,
            'material.specular': specular,
        }

if __name__ == "__main__":
    TestContext.ContextMainLoop()
