#! /usr/bin/env python
'''=Specular Highlights, Indexed Geometry, Directional Lighting=

[shader_6.py-screen-0001.png Screenshot]

This tutorial builds on earlier tutorials by adding:

    * specular lighting (Phong Lighting)
    * specular lighting (Blinn-Phong Lighting)
    * per-fragment lighting
    * Sphere geometry object (indexed rendering)

This tutorial completes the 
[http://en.wikipedia.org/wiki/Phong_shading Phong Shading]
rendering code that we started in the last tutorial by adding 
"specular" highlights to the material.  Specular highlights are 
basically "shininess", that is, the tendancy of a material to 
re-emit light *in a particular direction* based on the angle of 
incidence of the light ray.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
'''This is our only new import.  The Sphere geometry node 
generates a "compiled" piece of sphere geometry 
as a pair of two VBOs and a count that tells us how many vertices 
need to be rendered from the VBOs to render the geometry.  The first 
VBO contains the per-vertex data which is to be rendered, while the 
second contains indices into that first VBO which allows triangles 
to be generated which share the vertex records.  In "smooth" geometry 
vertices tend to be shared, so this rendering method tends to be 
more efficient than using expanded arrays of vertices.
'''
from OpenGLContext.scenegraph.basenodes import Sphere

class TestContext( BaseContext ):
    """Demonstrates use of attribute types in GLSL
    """
    def OnInit( self ):
        """Initialize the context"""
        '''== Phong and Blinn Reflectance ==

        A shiny surface will tend to have a "bright spot" at the point 
        on the surface where the angle of incidence for the reflected
        light ray and the viewer's ray are (close to) equal.  
        A perfect mirror would have the brights spot solely when the 
        two vectors are exactly equal, while a perfect Lambertian
        surface would have the "bright spot" spread across the entire
        surface.
        
        The Phong rendering process models this as a setting, traditionally
        called material "shininess" in Legacy OpenGL.  This setting acts 
        as a power which raises the cosine (dot product) of the 
        angle between the reflected ray and the eye.  The calculation of 
        the cosine (dot product) of the two angles requires that we do 
        a dot product of the two angles once for each vertex/fragment 
        for which we wish to calculate the specular reflectance, we also 
        have to find the angle of reflectance before we can do the 
        calculation:'''
        """
            L_dir = (V_pos-L_pos)
            R = 2N*(dot( N, L_dir))-L_dir
            // Note: in eye-coordinate system, Eye_pos == (0,0,0)
            Spec_factor = pow( dot( R, V_pos-Eye_pos ), shininess)
        """
        '''which, as we can see, involves the vertex position in a number 
        of stages of the operation, so requires recalculation all through 
        the rendering operation.
        
        There is, however, a simplified version of Phong Lighting called 
        [http://en.wikipedia.org/wiki/Blinn%E2%80%93Phong_shading_model Blinn-Phong]
        which notes that if we were to do all of our calculations in 
        "eye space", and were to assume that (as is normal), the eye 
        and light coordinates will not change for a rendering pass,
        (note: this limits us to directional lights!) we 
        can use a pre-calculated value which is the bisecting angle
        between the light-vector and the view-vector, called the 
        "half vector" to 
        perform approximately the same calculation.  With this value:'''
        """
            // note that in Eye coordinates, Eye_EC_dir == 0,0,-1
            H = normalize( Eye_EC_dir + Light_EC_dir )
            Spec_factor = pow( dot( H, N ), shininess )
        """
        '''Note: however, that the resulting Spec_factor is not *precisely*
        the same value as the original calculation, so the "shininess"
        exponent must be slightly lower to approximate the value that
        Phong rendering would achieve.  The value is, however, considered
        close to "real world" materials, so the Blinn method is generally 
        preferred to Phong.
        
        Traditionally, n_dot_pos would be cut off at 0.0, but that would 
        create extremely hard-edged cut-offs for specular color.  Here 
        we "fudge" the result by 0.05
        '''
        phong_weightCalc = """
        vec2 phong_weightCalc( 
            in vec3 light_pos, // light position
            in vec3 half_light, // half-way vector between light and view
            in vec3 frag_normal, // geometry normal
            in float shininess
        ) {
            // returns vec2( ambientMult, diffuseMult )
            float n_dot_pos = max( 0.0, dot( 
                frag_normal, light_pos
            ));
            float n_dot_half = 0.0;
            if (n_dot_pos > -.05) {
                n_dot_half = pow(max(0.0,dot( 
                    half_light, frag_normal
                )), shininess);
            }
            return vec2( n_dot_pos, n_dot_half);
        }		
        """
        '''We are going to use per-fragment rendering.
        As a result, our vertex shader becomes very simple, just arranging
        for the Normals to be varied across the surface.
        '''
        vertex = shaders.compileShader( 
        """
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;
        
        varying vec3 baseNormal;
        void main() {
            gl_Position = gl_ModelViewProjectionMatrix * vec4( 
                Vertex_position, 1.0
            );
            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
        }""", GL_VERTEX_SHADER)
        '''Our fragment shader looks much like our previous tutorial's 
        vertex shader.  As before, we have lots of uniform values,
        but now we also calculate the light's half-vector (in eye-space 
        coordinates).  The phong_weightCalc function does the core Blinn 
        calculation, and we simply use the resulting factor to add to 
        the colour value for the fragment.
        
        Note the use of the eye-coordinate-space to simplify the 
        half-vector calculation, the eye-space eye-vector is always 
        the same value (pointing down the negative Z axis), 
        and the eye-space eye-coordinate is always (0,0,0), so the 
        eye-to-vertex vector is always the eye-space vector position.
        '''
        fragment = shaders.compileShader( phong_weightCalc + """
        uniform vec4 Global_ambient;
        
        uniform vec4 Light_ambient;
        uniform vec4 Light_diffuse;
        uniform vec4 Light_specular;
        uniform vec3 Light_location;
        
        uniform float Material_shininess;
        uniform vec4 Material_specular;
        uniform vec4 Material_ambient;
        uniform vec4 Material_diffuse;
        
        varying vec3 baseNormal;
        void main() {
            // normalized eye-coordinate Light location
            vec3 EC_Light_location = normalize(
                gl_NormalMatrix * Light_location
            );
            // half-vector calculation 
            vec3 Light_half = normalize(
                EC_Light_location - vec3( 0,0,-1 )
            );
            vec2 weights = phong_weightCalc(
                EC_Light_location,
                Light_half,
                baseNormal,
                Material_shininess
            );
            
            gl_FragColor = clamp( 
            (
                (Global_ambient * Material_ambient)
                + (Light_ambient * Material_ambient)
                + (Light_diffuse * Material_diffuse * weights.x)
                // material's shininess is the only change here...
                + (Light_specular * Material_specular * weights.y)
            ), 0.0, 1.0);
        }
        """, GL_FRAGMENT_SHADER)
        
        self.shader = shaders.compileProgram(vertex,fragment)
        '''Here's the call that creates the two VBOs and the 
        count of records to render from them. If you're curious 
        you can read through the source code of the 
        OpenGLContext.scenegraph.quadrics module to read the 
        mechanism that generates the values.
        
        The sphere is a simple rendering mechanism, as for a 
        unit-sphere at the origin, the sphere's normals are the 
        same as the sphere's vertex coordinate.  The complexity 
        comes primarily in generating the triangle indices that 
        link the points generated.
        '''
        self.coords,self.indices,self.count = Sphere( 
            radius = 1 
        ).compile()
        '''We have a few more uniforms to control the specular 
        components.  Real-world coding would also calculate the 
        light's half-vector and provide it as a uniform (so that 
        it would only need to be calculated once), but we are going 
        to do the half-vector calculation in the shader to make 
        it obvious what is going on.  The legacy OpenGL pipeline 
        provides the value pre-calculated as part of the light structure 
        in GLSL.
        '''
        for uniform in (
            'Global_ambient',
            'Light_ambient','Light_diffuse','Light_location',
            'Light_specular',
            'Material_ambient','Material_diffuse',
            'Material_shininess','Material_specular',
        ):
            location = glGetUniformLocation( self.shader, uniform )
            if location in (None,-1):
                print 'Warning, no uniform: %s'%( uniform )
            setattr( self, uniform+ '_loc', location )
        for attribute in (
            'Vertex_position','Vertex_normal',
        ):
            location = glGetAttribLocation( self.shader, attribute )
            if location in (None,-1):
                print 'Warning, no attribute: %s'%( uniform )
            setattr( self, attribute+ '_loc', location )
    
    def Render( self, mode = None):
        """Render the geometry for the scene."""
        BaseContext.Render( self, mode )
        glUseProgram(self.shader)
        try:
            '''==Indexed VBO Rendering==
            
            You'll notice here that we are binding two different VBO 
            objects.  As we mentioned above, the Sphere renderer 
            generated both VBOs, but doesn't the second binding replace 
            the first binding?  That is, why doesn't OpenGL try to read 
            the Vertex data out of the indices VBO?
            
            OpenGL defines multiple binding "targets" for VBOs, the 
            first VBO (vertices) was bound to the GL_ARRAY_BUFFER
            target (the default for the class), which is used for reading 
            per-vertex data arrays, while the indices buffer was defined
            as targetting the GL_ELEMENT_ARRAY_BUFFER, which is used
            solely for reading indices.
            
            Each target can be bound to a different VBO, and thus we can
            bind both VBOs at the same time without confusion.
            '''
            self.coords.bind()
            self.indices.bind()
            '''Here, being lazy, we use the numpy array's nbytes value 
            to specify the stride between records.  The VBO object has 
            a "data" value which is the data-set which was initially 
            passed to the VBO constructor.  The first element in this 
            array is a single vertex record.  This array happens to have 
            8 floating-point values (24 bytes), the first three being 
            the vertex position, the next two being the texture coordinate 
            and the last three being the vertex normal.  We'll ignore 
            the texture coordinate for now.
            '''
            stride = self.coords.data[0].nbytes
            try:
                glUniform4f( self.Global_ambient_loc, .05,.05,.05,.1 )
                glUniform4f( self.Light_ambient_loc, .1,.1,.1, 1.0 )
                glUniform4f( self.Light_diffuse_loc, .25,.25,.25,1 )
                '''We set up a yellow-ish specular component in the 
                light and move it to rest "just over our right shoulder"
                in relation to the initial camera.'''
                glUniform4f( self.Light_specular_loc, 0.0,1.0,0,1 )
                glUniform3f( self.Light_location_loc, 6,2,4 )
                
                glUniform4f( self.Material_ambient_loc, .1,.1,.1, 1.0 )
                glUniform4f( self.Material_diffuse_loc, .15,.15,.15, 1 )
                '''We make the material have a bright specular white 
                colour and an extremely "shiny" surface.  The shininess 
                value has the effect of reducing the area of the
                highlight, as the cos of the angle is raised 
                to the power of the (fractional) shininess.'''
                glUniform4f( self.Material_specular_loc, 1.0,1.0,1.0, 1.0 )
                glUniform1f( self.Material_shininess_loc, .95)
                glEnableVertexAttribArray( self.Vertex_position_loc )
                glEnableVertexAttribArray( self.Vertex_normal_loc )
                glVertexAttribPointer( 
                    self.Vertex_position_loc, 
                    3, GL_FLOAT,False, stride, self.coords
                )
                glVertexAttribPointer( 
                    self.Vertex_normal_loc, 
                    3, GL_FLOAT,False, stride, self.coords+(5*4)
                )
                '''Here we introduce the OpenGL call which renders via 
                an index-array rather than just rendering vertices in 
                definition order.  The last two arguments tell OpenGL 
                what data-type we've used for the indices (the Sphere 
                renderer uses shorts).  The indices VBO is actually 
                just passing the value c_void_p( 0 ) (i.e. a null pointer),
                which causes OpenGL to use the currently bound VBO for 
                the GL_ELEMENT_ARRAY_BUFFER target.
                '''
                glDrawElements(
                    GL_TRIANGLES, self.count,
                    GL_UNSIGNED_SHORT, self.indices
                )
            finally:
                '''Note the need to unbind *both* VBOs, we have to free 
                *both* VBO targets to avoid any other rendering operation 
                from trying to access the VBOs.'''
                self.coords.unbind()
                self.indices.unbind()
                glDisableVertexAttribArray( self.Vertex_position_loc )
                glDisableVertexAttribArray( self.Vertex_normal_loc )
        finally:
            glUseProgram( 0 )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''Our per-fragment Blinn-Phong rendering engine is a very simplistic 
model of real-world lighting, and is currently limited to a single
directional light.  Our next tutorial will begin to 
reduce these "simplifying assumptions".'''
