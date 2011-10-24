#! /usr/bin/env python
'''=Diffuse, Ambient, Directional Lighting=

[shader_5.py-screen-0001.png Screenshot]
[shader_5.py-screen-0002.png Screenshot]

This tutorial builds on earlier tutorials by adding:

    * ambient lighting 
    * diffuse lighting 
    * directional lights (e.g. the Sun)
    * normals, the normal matrix

Lighting is one of the most complex aspects of the rendering 
process.  No-one has yet come up with a "perfect" simulation 
of rendering for use in real-time graphics (even non-real-time 
graphics haven't really solved the problem for every material).

So every OpenGL renderer is an approximation of what a particular 
material should look like under some approximation of a particular 
lighting environment.  Traditional (legacy) OpenGL had a particular 
lighting model which often "worked" for simple visualizations of 
geometry.  This tutorial is going to show you how to start creating 
a similar lighting effect (known as
[http://en.wikipedia.org/wiki/Phong_shading Phong Shading], though 
we will not introduce the specular components until the next 
tutorial).

== Ambient Lighting ==

Ambient lighting is used to simulate the "radiant" effect in lighting,
that is, the effect of light which is "bouncing around" the environment 
which otherwise isn't accounted for by your lighting model.

In Legacy OpenGL, ambient light was handled as a setting declaring
each surface's ambient reflectance (a colour), with a set of two 
"light sources" which would be reflected.

    * Global ambient light
    * Per-light ambient contribution

The global light can be thought of as "light that is always there",
even if there are no active lights, so some (ambient) light that is 
always present in the environment even if no defined lights are 
active.  Per-light ambient contributions are only calculated if the 
light is active, but otherwise works identically to global ambient.
You can think of this as "how much turning on this light increases
the global ambient light level".

The ambient contribution for each material here is simply:

    Light ambient * Material_ambient 

there is no other information involved in the ambient light 
calculation.  It doesn't matter where the light is in relation 
to the material, or the angle of incidence of the light, or the 
angle at which you are viewing the material.

Our shaders are going to assume that there is only 1 active non-global 
ambient light.  Legacy OpenGL allows at least 8 active lights, all 
of which would be involved in the ambient light calculations
(when enabled).

The material's ambient value can be thought of as "how much of 
the ambient light does the material re-emit" (as opposed to absorbing).
Note, that all of the ambient values here are 4-component colours, so 
the material's ambient value may actually change the colour of the 
ambient reflected light.  Similarly, a strongly coloured ambient light 
will tend to give all materials a strong "undercast" of that colour.
'''
from OpenGLContext import testingcontext
BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
from OpenGLContext.events.timer import Timer

class TestContext( BaseContext ):
    """Demonstrates use of attribute types in GLSL
    """
    def OnInit( self ):
        """Initialize the context"""
        '''== Diffuse Lighting ==

        Diffuse lighting is used to simulate re-emission from a surface
        where the re-emittance isn't "ordered" (that is, the re-emitted
        light is is diffused).
        
        A "non-shiny" surface which re-emits everything that hits it
        (think snow, or a rough wooden board, for instance) would have 
        a very high "diffuse"
        lighting value.  A diffuse surface  emits light in *all*
        directions whenever hit by a light, but the amount 
        of light it emits is controlled by the angle at which the light
        hits the surface.

        (Technically this is called
        [http://en.wikipedia.org/wiki/Lambertian_reflectance Lambertian Reflectance]).

        In order to calculate the diffuse lighting value, we need a number 
        of pieces of information:

            * the angle between the surface and the light
            * the diffuse intensity of the light 
            * the diffuse reflectance of the material 

        To calculate the angle between the surface and the light, we need 
        some way of determining which direction any particular part of a 
        surface is pointing.  In OpenGL this has been traditionally 
        accomplished by passing in a Normal value for each vertex and 
        interpolating those Normals across the surface.

        Unlike the Normals you calculated in algebra and geometry class,
        the Normal on a particular vertex does *not* have to be the cross 
        product of two adjacent edges.  Instead, it is the value that 
        a human being has assigned that makes the vertex look right.
        It will often be a blending of the "natural" (calculated) Normals 
        of the adjacent faces, as this will tend to create a "smooth" look 
        that makes the two faces appear to be one continuous surface.

        Once we have a Normal, we also need the light's direction in order 
        to calculate the angle between them.  For this tutorial we'll use 
        the simplest possible light, an infinitely far "directional" light 
        which loosely models the behaviour of sunlight on the surface of
        the Earth.

        This light has a direction, with all rays from the light 
        considered to be travelling in parallel in this direction.  Thus
        the relative position of the light (which is "infinitely" far away,
        which means all of the relative positions are the same) 
        has no effect on the angle at which the light's rays will strike 
        a surface. A directional light is, in essence, just a normalized 
        vector which points from the "location" of the light to the origin.

        With our normal and our directional light, we can apply Lambert's 
        law to calculate the diffuse component multiplier for any given 
        vertex.  Lambert's law looks for the cosine of the two vectors 
        (the Normal and the Light Location vector), which is calculated 
        by taking the dot product of the two (normalized) vectors.
        
        Our GLSL function phong_weightCalc (below) will calculate the factor 
        which controls the diffuse light contribution of a single light.
        Both of the values passed in must be *normalized* vectors.
        '''
        
        phong_weightCalc = """
        float phong_weightCalc( 
            in vec3 light_pos, // light position
            in vec3 frag_normal // geometry normal
        ) {
            // returns vec2( ambientMult, diffuseMult )
            float n_dot_pos = max( 0.0, dot( 
                frag_normal, light_pos
            ));
            return n_dot_pos;
        }		
        """
        '''Our vertex shader is going to do all the work for us,
        it defines a large number of uniform values that store the 
        various light and material parameters.  We also define two 
        per-vertex attributes to store the position and normal
        assigned by the user.
        '''
        vertex = shaders.compileShader( phong_weightCalc + 
        """
        uniform vec4 Global_ambient;
        
        uniform vec4 Light_ambient;
        uniform vec4 Light_diffuse;
        uniform vec3 Light_location;
        
        uniform vec4 Material_ambient;
        uniform vec4 Material_diffuse;
        
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;
        
        varying vec4 baseColor;
        void main() {
            gl_Position = gl_ModelViewProjectionMatrix * vec4( 
                Vertex_position, 1.0
            );
            
            vec3 EC_Light_location = gl_NormalMatrix * Light_location;
            float diffuse_weight = phong_weightCalc(
                normalize(EC_Light_location),
                normalize(gl_NormalMatrix * Vertex_normal)
            );
            
            baseColor = clamp( 
            (
                // global component 
                (Global_ambient * Material_ambient)
                // material's interaction with light's contribution 
                // to the ambient lighting...
                + (Light_ambient * Material_ambient)
                // material's interaction with the direct light from 
                // the light.
                + (Light_diffuse * Material_diffuse * diffuse_weight)
            ), 0.0, 1.0);
        }""", GL_VERTEX_SHADER)
        '''The actual lighting calculation is simply adding the various 
        contributors together in order to find the final colour, then 
        clamping the result to the range 0.0 to 1.0.  We could have let 
        OpenGL do this clamping itself, the call is done here simply 
        to illustrate the effect.
        
        == Eye Space or Not? ==
        
        In our vertex shader, we actually use the "eye space" forms 
        of the two vectors for the angular calculation.  For Lambertian
        Reflectance we could as easily have left the coordinates in 
        "model space" to do the calculations:'''
        """			
        vec2 weights = phong_weightCalc(
            normalize(Light_location),
            normalize(Vertex_normal)
        );"""
        '''Most documentation, however, describes most lighting
        calculations in "eye space" forms, as it tends to simplify 
        the calculations for more involved lighting.
        
        Our fragment shader here is extremely simple.  We could
        actually do per-fragment lighting calculations, but it wouldn't
        particularly improve our rendering with simple diffuse shading.
        '''
        fragment = shaders.compileShader("""
        varying vec4 baseColor;
        void main() {
            gl_FragColor = baseColor;
        }
        """, GL_FRAGMENT_SHADER)
        
        self.shader = shaders.compileProgram(vertex,fragment)
        '''We're going to create slightly less "flat" geometry for this 
        lesson, we'll create a set of 6 faces in a "bow window" 
        arrangement that makes it easy to see the effect of the direct 
        lighting.'''
        self.vbo = vbo.VBO(
            array( [
                [ -1, 0, 0, -1,0,1],
                [  0, 0, 1, -1,0,2],
                [  0, 1, 1, -1,0,2],
                [ -1, 0, 0, -1,0,1],
                [  0, 1, 1, -1,0,2],
                [ -1, 1, 0, -1,0,1],
                
                [  0, 0, 1, -1,0,2],
                [  1, 0, 1, 1,0,2],
                [  1, 1, 1, 1,0,2],
                [  0, 0, 1, -1,0,2],
                [  1, 1, 1, 1,0,2],
                [  0, 1, 1, -1,0,2],
                
                [  1, 0, 1, 1,0,2],
                [  2, 0, 0, 1,0,1],
                [  2, 1, 0, 1,0,1],
                [  1, 0, 1, 1,0,2],
                [  2, 1, 0, 1,0,1],
                [  1, 1, 1, 1,0,2],
            ],'f')
        )
        '''Since we have so many more uniforms and attributes, we'll 
        use a bit of iteration to set up the values for ourselves.'''
        for uniform in (
            'Global_ambient',
            'Light_ambient','Light_diffuse','Light_location',
            'Material_ambient','Material_diffuse',
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
            self.vbo.bind()
            try:
                '''We add a strong red tinge so you can see the 
                global ambient light's contribution.'''
                glUniform4f( self.Global_ambient_loc, .3,.05,.05,.1 )
                '''In legacy OpenGL we would be using different 
                special-purpose calls to set these variables.'''
                glUniform4f( self.Light_ambient_loc, .2,.2,.2, 1.0 )
                glUniform4f( self.Light_diffuse_loc, 1,1,1,1 )
                glUniform3f( self.Light_location_loc, 2,2,10 )
                
                glUniform4f( self.Material_ambient_loc, .2,.2,.2, 1.0 )
                glUniform4f( self.Material_diffuse_loc, 1,1,1, 1 )
                '''We only have the two per-vertex attributes'''
                glEnableVertexAttribArray( self.Vertex_position_loc )
                glEnableVertexAttribArray( self.Vertex_normal_loc )
                stride = 6*4
                glVertexAttribPointer( 
                    self.Vertex_position_loc, 
                    3, GL_FLOAT,False, stride, self.vbo 
                )
                glVertexAttribPointer( 
                    self.Vertex_normal_loc, 
                    3, GL_FLOAT,False, stride, self.vbo+12
                )
                glDrawArrays(GL_TRIANGLES, 0, 18)
            finally:
                self.vbo.unbind()
                '''Need to cleanup, as always.'''
                glDisableVertexAttribArray( self.Vertex_position_loc )
                glDisableVertexAttribArray( self.Vertex_normal_loc )
        finally:
            glUseProgram( 0 )

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''Our next tutorial will cover the rest of the Phong rendering 
algorithm, by adding "specular highlights" (shininess) to the 
surface.'''
