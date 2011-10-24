#! /usr/bin/env python
'''=Shader Scenegraph Nodes=

[shader_12.py-screen-0001.png Screenshot]

This tutorial:

    * use scenegraph GLSL shader nodes to simplify the code

We've been manually coding all of our shader, VBO and similar calls,
while this is useful as a learning exercise, real-world code isn't
likely to want to use raw calls everywhere.  In this tutorial we'll
translate our previous code to use the
[http://pyopengl.sourceforge.net/pydoc/OpenGLContext.scenegraph.shaders.html OpenGLContext.scenegraph.shaders]
nodes.  These provide a set of declarative structures which can be
used to create shader-based geometry with explicit support for
libraries of reusable code.

We're going to use our previous tutorial as the base for this new
code-base...
'''
from shader_11 import TestContext as BaseContext
from OpenGL.GL import *
from OpenGL.arrays import vbo
from OpenGLContext.arrays import *
from OpenGL.GL import shaders
'''OpenGLContext registers the shader nodes as "core" VRML97 nodes, so
we can just import the base node-set.'''
from OpenGLContext.scenegraph.basenodes import *

class TestContext( BaseContext ):
    """Shows conversion of tutorial code to use shader nodes."""

    def OnInit( self ):
        """Initialize the context"""
        '''We want the same lights as we used in the last tutorial, and we're
        going to use the same code to generate a data-array for the light-array
        uniform for our shader...'''
        self.lights = self.createLights()
        self.LIGHTS = array([
            self.lightAsArray(l)
            for l in self.lights
        ],'f')
        '''Our shader constant declarations are the same, so we use the previous
        definitions and update them in the same way.'''
        self.shader_constants['LIGHT_COUNT'] = len(self.lights)

        '''==GLSLImport Nodes==

        Our first shader node is the GLSLImport node.  This represents an
        included source-code file for use by a shader.  We'll use the three
        pieces of code we saved out to resources and files via imports here.
        The first import is our simple file of tutorial-specific light
        calculations.  The url field is actually a list-of-urls field, and
        can load from anything urllib can handle.'''
        light_preCalc = GLSLImport( url='_shader_tut_lightprecalc.vert' )
        '''We made our two reusable blinn-phong functions into OpenGLContext
        resources precisely so that we could eventually use "resource" urls
        to reference them.'''
        phong_preCalc = GLSLImport( url="res://phongprecalc_vert" )
        phong_weightCalc = GLSLImport( url="res://phongweights_frag" )
        '''The GLSLImport can also handle directly specifying the source-code,
        rather than loading from a URL.  Here we create a resuable import node
        which declares our light array and varying values.'''
        lightConst = GLSLImport( source = "\n".join([
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
        )
        '''==GLSLObject, GLSLShader==

        The GLSLObject is a particular shader implementation (currently the
        only implementation in OpenGLContext) of Shaders which uses GLSL to
        do compilation.  The GLSLObject can be "rendered" (enabled) with a
        single call that triggers each of the attached nodes to be configured
        for use with the object.

        The GLSLObject declares a set of Uniform nodes, each of
        which maps to one of the shader-object's coded uniforms.  These
        uniforms will automatically look up and cache their uniform locations,
        as well as performing data-conversions on their values and providing
        the data-size parameters for glUniformXfv() calls.  There is one
        Uniform sub-class for each of the glUniformXYv calls, including the
        float and integer variants.

        The GLSLObject also declares a set of TextureUniform nodes which behave
        much like regular Uniform values, save that their "value" is an
        ImageTexture node which is rendered (loaded) into a texture unit when
        the GLSLObject is rendered.  The GLSLObject will assign the texture
        uniforms to the texture units in order as it renders.

        Lastly, the GLSLObject declares a set of GLSLShader objects which
        represent the component shaders which make up your shader object.  These
        nodes can, like the GLSLImport use the url property to load from files,
        web-sites or resources, or they can use the source property to declare
        the source inline.  The GLSLShader declares a set of GLSLImport objects
        whose source is concatenated with the GLSLShader's source during
        compilation.  Note that the GLSLShader will not be compiled until/unless
        *all* of the GLSLImport and the GLSLShader itself have defined source
        values.
        '''
        self.glslObject = GLSLObject(
            uniforms = [
                FloatUniform1f(name="material.shininess", value=.5 ),
                FloatUniform4f(name="material.ambient", value=(.1,.1,.1,1.0) ),
                FloatUniform4f(name="material.diffuse", value=(1.0,1.0,1.0,1.0) ),
                FloatUniform4f(name="material.specular", value=(.4,.4,.4,1.0) ),
                FloatUniform4f(name="Global_ambient", value=(.1,.1,.1,1.0) ),
                FloatUniform4f(name="lights" ),
            ],
            textures = [
                TextureUniform(name="diffuse_texture", value=ImageTexture(
                    url="marbleface.jpeg",
                )),
            ],
            shaders = [
                GLSLShader(
                    imports = [
                        lightConst,
                        phong_preCalc,
                        light_preCalc,
                    ],
                    source = [
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
                        }"""
                    ],
                    type='VERTEX'
                ),
                GLSLShader(
                    imports = [
                        lightConst,
                        phong_weightCalc,
                    ],
                    source = [
                        """
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
                                    abs(Light_distance[i]), // see note tutorial 9
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
                        """
                    ],
                    type='FRAGMENT',
                ),
            ],
        )
        '''In our previous tutorials, we used the Sphere node's compile() method
        to retrieve precompiled VBOs.  The Shader module has code which will
        manage our attributes for us, but it needs raw arrays, so we ask the
        Sphere for the raw arrays instead of the VBOs.'''
        coords,indices = Sphere(
            radius = 1
        ).compileArrays()
        '''The two common VBO types (vertex and index) are separate node types
        in the Shaders module.  We create a buffer for each here, the coords
        buffer will be referenced by all of our attributes.  The index buffer
        normally would be used by a ShaderSlice node on a ShaderGeometry node
        to automate the rendering process, we'll call it manually instead.'''
        self.coords = ShaderBuffer( buffer = coords )
        self.indices = ShaderIndexBuffer( buffer = indices )
        '''To call the draw command we need to know how many indices are to
        be rendered, so we store the value here.'''
        self.count = len(indices)
        '''Our attribute setup needs to know the stride for the arrays.'''
        stride = coords[0].nbytes
        '''Our attribute nodes work very similarly to the Uniform nodes, they
        will automatically lookup their locations.  The buffer attribute is
        the ShaderBuffer which holds the vertex values.  The isCoord attribute
        tells OpenGLContext to use this attribute for calculating bounding boxes
        for the geometry for use in frustum culling.
        '''
        self.attributes = [
            ShaderAttribute(
                name = 'Vertex_position',
                offset = 0,
                stride = stride,
                buffer = self.coords,
                isCoord = True,
            ),
            ShaderAttribute(
                name = 'Vertex_texture_coordinate',
                offset = 4*3,
                stride = stride,
                buffer = self.coords,
                size = 2,
                isCoord = False,
            ),
            ShaderAttribute(
                name = 'Vertex_normal',
                offset = 4*5,
                stride = stride,
                buffer = self.coords,
                isCoord = False,
            ),
        ]
        '''Our appearance node no longer declares a texture attribute.  Shader
        texture usage is far more complex than the VRML97 appearance node's model
        can support.'''
        self.appearance = Appearance(
            material = Material(
                diffuseColor = (1,1,1),
                ambientIntensity = .1,
                shininess = .5,
            ),
        )

    def Render( self, mode = None):
        """Render the geometry for the scene."""
        if not mode.visible:
            return
        '''We are going to update the lights array on every frame, normally we'd
        cache the whole array and only update if there was a change.  This is
        exactly what we did in our previous tutorial.'''
        for i,light in enumerate( self.lights ):
            self.LIGHTS[i] = self.lightAsArray( light )
        '''With our newly-calculated light array, we configure the appropriate
        uniform with the data-array.  The GLSLObject has a getVariable( name )
        method which returns the attribute-or-uniform of the given name.
        Assigning to the variable's value attribute will cause the value to
        be passed in when the GLSLObject is rendered.'''
        self.glslObject.getVariable( 'lights' ).value = self.LIGHTS
        '''We do the same thing with our material configuration.  We use our
        previous code to calculate the desired values and then configure the
        uniform variables with those values.'''
        for key,value in self.materialFromAppearance(
            self.appearance, mode
        ).items():
            self.glslObject.getVariable( key ).value = value

        '''OpenGLContext rendering nodes will often return "tokens" which
        are to be passed back to the node after the rendering pass to disable
        the changes made.  The GLSLObject produces one of these when rendered.
        The rendering will compile the shaders (reporting errors if they occur),
        bind the object, and iterate through the textures and uniforms
        configuring them for use with the shader.
        '''
        token = self.glslObject.render( mode )
        tokens = [  ]
        try:
            '''As mentioned above, our indices ShaderIndexBuffer would normally
            be rendered via a ShaderGeometry/ShaderSlice node.  We're going to
            manually trigger it here.'''
            vbo = self.indices.bind(mode)
            '''Again, normally the ShaderGeometry/ShaderSlice would trigger the
            attribute nodes.  We iterate over them passing in the shader object
            to which to attach themselves.  The attributes will generally return
            tokens to disable the attribute configuration after rendering.'''
            for attribute in self.attributes:
                token = attribute.render( self.glslObject, mode )
                if token:
                    tokens.append( (attribute, token) )
            '''And our actual drawing code.  You will note that the *type* of the
            indices has changed.  The ShaderIndexBuffer is intended to be generic,
            so it uses full 32-bit unsigned ints rather than 16-bit ints and has
            up-converted our array of 16-bit ints when we created it.'''
            glDrawElements(
                GL_TRIANGLES, self.count,
                GL_UNSIGNED_INT, vbo
            )
        finally:
            '''We ask each thing which returned a rendering token to disable
            itself after the rendering pass.'''
            for attribute,token in tokens:
                attribute.renderPost( self.glslObject, mode, token )
            self.glslObject.renderPost( token, mode )
            '''The index-array VBO also needs to be unbound.'''
            vbo.unbind()

if __name__ == "__main__":
    TestContext.ContextMainLoop()
'''Note: OpenGLContext's shader nodes are intended to provide a way to play with
shaders directly using declarative forms that are scenegraph-compatible.  The
module is still in active development, so expect that this tutorial may be updated
as new functionality is introduced.'''
