#! /usr/bin/env python
'''=Instanced Geometry and Texture Buffer Extensions=

[shader_instanced.py-screen-0001.png Screenshot]

This tutorial demonstrates instanced geometry rendering: one draw call that
puts many copies of the same mesh on screen, each with its own offset read
from a texture buffer.

In this tutorial we'll learn:

    * how to use an instanced draw to put lots of geometry on screen
    * how a texture buffer object and texelFetch give each copy its own data
    * how a shader takes the camera as explicit matrix uniforms
'''

import builtins
from OpenGLContext import testingcontext

BaseContext = testingcontext.getInteractive()
from OpenGL.GL import *
from OpenGL.GL.shaders import compileProgram, compileShader
from OpenGLContext.arrays import *
from OpenGL.arrays import vbo
from numpy import random

# Shader constants for lighting
LIGHT_COUNT = 3
LIGHT_SIZE = 7
AMBIENT = 0
DIFFUSE = 1
SPECULAR = 2
POSITION = 3
ATTENUATION = 4
SPOT_PARAMS = 5
SPOT_DIR = 6

# Vertex shader using modern GLSL
VERTEX_SHADER = """#version 330 core

// Vertex inputs
in vec3 Vertex_position;
in vec3 Vertex_normal;
in vec2 Vertex_texture_coordinate;

// Uniforms
uniform mat4 modelViewProjection;
uniform mat4 modelView;
uniform mat3 normalMatrix;
uniform samplerBuffer offsets_table;
uniform vec4 lights[%(LIGHT_COUNT)d * %(LIGHT_SIZE)d];

// Outputs to fragment shader
out vec3 baseNormal;
out vec2 texCoord;
out vec3 EC_Light_half[%(LIGHT_COUNT)d];
out vec3 EC_Light_location[%(LIGHT_COUNT)d];
out float Light_distance[%(LIGHT_COUNT)d];

// Light pre-calculation
void calculateLight(int lightIndex, vec3 vertex_position) {
    int j = lightIndex * %(LIGHT_SIZE)d;
    vec4 light_position = lights[j + %(POSITION)d];

    if (light_position.w == 0.0) {
        // Directional light
        EC_Light_location[lightIndex] = normalize(normalMatrix * light_position.xyz);
        Light_distance[lightIndex] = 0.0;
    } else {
        // Positional light
        vec3 ms_vec = light_position.xyz - vertex_position;
        vec3 light_direction = normalMatrix * ms_vec;
        EC_Light_location[lightIndex] = normalize(light_direction);
        Light_distance[lightIndex] = abs(length(ms_vec));
    }
    // Half-vector calculation
    EC_Light_half[lightIndex] = normalize(EC_Light_location[lightIndex] - vec3(0, 0, -1));
}

void main() {
    // Get per-instance offset from texture buffer
    vec3 offset = texelFetch(offsets_table, gl_InstanceID).xyz;
    vec3 final_position = Vertex_position + offset;

    // Transform position
    gl_Position = modelViewProjection * vec4(final_position, 1.0);

    // Transform normal
    baseNormal = normalMatrix * normalize(Vertex_normal);

    // Pass through texture coordinate
    texCoord = Vertex_texture_coordinate;

    // Calculate lighting for each light
    for (int i = 0; i < %(LIGHT_COUNT)d; i++) {
        calculateLight(i, final_position);
    }
}
""" % {
    "LIGHT_COUNT": LIGHT_COUNT,
    "LIGHT_SIZE": LIGHT_SIZE,
    "POSITION": POSITION,
}

# Fragment shader using modern GLSL
FRAGMENT_SHADER = """#version 330 core

// Inputs from vertex shader
in vec3 baseNormal;
in vec2 texCoord;
in vec3 EC_Light_half[%(LIGHT_COUNT)d];
in vec3 EC_Light_location[%(LIGHT_COUNT)d];
in float Light_distance[%(LIGHT_COUNT)d];

// Uniforms
uniform vec4 lights[%(LIGHT_COUNT)d * %(LIGHT_SIZE)d];
uniform sampler2D diffuse_texture;

struct Material {
    vec4 ambient;
    vec4 diffuse;
    vec4 specular;
    float shininess;
};
uniform Material material;
uniform vec4 Global_ambient;

// Output
out vec4 fragColor;

// Phong weight calculation
vec3 phong_weightCalc(
    vec3 light_pos,
    vec3 half_light,
    vec3 frag_normal,
    float shininess,
    float distance,
    vec4 attenuations,
    vec4 spot_params,
    vec4 spot_dir
) {
    float n_dot_pos = max(0.0, dot(frag_normal, light_pos));
    float n_dot_half = 0.0;

    if (n_dot_pos > -0.05) {
        n_dot_half = pow(max(0.0, dot(half_light, frag_normal)), shininess);
    }

    float attenuation = 1.0;
    if (distance != 0.0) {
        float dist_atten = attenuations.x + attenuations.y * distance +
                          attenuations.z * distance * distance;
        if (dist_atten > 0.0) {
            attenuation = 1.0 / dist_atten;
        }
        if (spot_params.w != 0.0) {
            float spot_effect = dot(normalize(spot_dir.xyz), -light_pos);
            if (spot_effect > spot_params.x) {
                attenuation *= pow(spot_effect, spot_params.y);
            } else {
                attenuation = 0.0;
            }
        }
    }

    return vec3(attenuation, n_dot_pos * attenuation, n_dot_half * attenuation);
}

void main() {
    fragColor = Global_ambient * material.ambient;

    vec4 texDiffuse = texture(diffuse_texture, texCoord);
    texDiffuse = mix(material.diffuse, texDiffuse, 0.5);

    vec3 normal = normalize(baseNormal);

    for (int i = 0; i < %(LIGHT_COUNT)d; i++) {
        int j = i * %(LIGHT_SIZE)d;
        vec3 weights = phong_weightCalc(
            normalize(EC_Light_location[i]),
            normalize(EC_Light_half[i]),
            normal,
            material.shininess,
            abs(Light_distance[i]),
            lights[j + %(ATTENUATION)d],
            lights[j + %(SPOT_PARAMS)d],
            lights[j + %(SPOT_DIR)d]
        );
        fragColor += lights[j + %(AMBIENT)d] * material.ambient * weights.x;
        fragColor += lights[j + %(DIFFUSE)d] * texDiffuse * weights.y;
        fragColor += lights[j + %(SPECULAR)d] * material.specular * weights.z;
    }
}
""" % {
    "LIGHT_COUNT": LIGHT_COUNT,
    "LIGHT_SIZE": LIGHT_SIZE,
    "AMBIENT": AMBIENT,
    "DIFFUSE": DIFFUSE,
    "SPECULAR": SPECULAR,
    "ATTENUATION": ATTENUATION,
    "SPOT_PARAMS": SPOT_PARAMS,
    "SPOT_DIR": SPOT_DIR,
}


class TestContext(BaseContext):
    """Demonstrates instanced rendering with modern GLSL."""

    def OnInit(self):
        """Initialize the context"""
        # Compile shaders
        self.shader = compileProgram(
            compileShader(VERTEX_SHADER, GL_VERTEX_SHADER),
            compileShader(FRAGMENT_SHADER, GL_FRAGMENT_SHADER),
        )

        # The vertex array object the attribute pointers are recorded into.
        self.vao = glGenVertexArrays(1)

        # Get uniform locations
        self.mvp_loc = glGetUniformLocation(self.shader, "modelViewProjection")
        self.mv_loc = glGetUniformLocation(self.shader, "modelView")
        self.nm_loc = glGetUniformLocation(self.shader, "normalMatrix")
        self.lights_loc = glGetUniformLocation(self.shader, "lights")
        self.texture_loc = glGetUniformLocation(self.shader, "diffuse_texture")
        self.offsets_loc = glGetUniformLocation(self.shader, "offsets_table")

        self.ambient_loc = glGetUniformLocation(self.shader, "material.ambient")
        self.diffuse_loc = glGetUniformLocation(self.shader, "material.diffuse")
        self.specular_loc = glGetUniformLocation(self.shader, "material.specular")
        self.shininess_loc = glGetUniformLocation(self.shader, "material.shininess")
        self.global_ambient_loc = glGetUniformLocation(self.shader, "Global_ambient")

        # Get attribute locations
        self.position_loc = glGetAttribLocation(self.shader, "Vertex_position")
        self.normal_loc = glGetAttribLocation(self.shader, "Vertex_normal")
        self.texcoord_loc = glGetAttribLocation(
            self.shader, "Vertex_texture_coordinate"
        )

        # Create instance offset data
        hardlimit = glGetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE)
        count = builtins.min(15000, hardlimit // 16)
        print("Limiting to %s instances" % count)

        scale = [40, 40, 40, 0]
        offset = [-20, -20, -40, 1]
        self.offset_array = (random.random(size=(count, 4)) * scale + offset).astype(
            "f"
        )
        self.instance_count = count

        # Create texture buffer for offsets
        self.offset_buffer = glGenBuffers(1)
        glBindBuffer(GL_TEXTURE_BUFFER, self.offset_buffer)
        glBufferData(
            GL_TEXTURE_BUFFER,
            self.offset_array.nbytes,
            self.offset_array,
            GL_STATIC_DRAW,
        )

        self.offset_texture = glGenTextures(1)
        glBindTexture(GL_TEXTURE_BUFFER, self.offset_texture)
        glTexBuffer(GL_TEXTURE_BUFFER, GL_RGBA32F, self.offset_buffer)

        # Create sphere geometry
        from OpenGLContext.scenegraph.basenodes import Sphere

        coords, indices = Sphere(radius=0.25, phi=pi / 8.0).compileArrays()

        self.vertex_vbo = vbo.VBO(coords)
        self.index_vbo = vbo.VBO(indices, target=GL_ELEMENT_ARRAY_BUFFER)
        self.index_count = len(indices)

        print(
            "Each sphere has %d triangles, total of %d triangles"
            % (self.index_count // 3, self.index_count // 3 * count)
        )

        # Load texture
        from OpenGLContext.scenegraph.imagetexture import ImageTexture

        self.texture_node = ImageTexture(url="marbleface.jpeg")

        # Set up lights (simple setup with 3 lights)
        self.lights_data = zeros((LIGHT_COUNT * LIGHT_SIZE, 4), "f")
        # Light 0 - directional
        self.lights_data[0 * LIGHT_SIZE + AMBIENT] = [0.05, 0.05, 0.05, 1.0]
        self.lights_data[0 * LIGHT_SIZE + DIFFUSE] = [0.8, 0.8, 0.8, 1.0]
        self.lights_data[0 * LIGHT_SIZE + SPECULAR] = [1.0, 1.0, 1.0, 1.0]
        self.lights_data[0 * LIGHT_SIZE + POSITION] = [
            1.0,
            1.0,
            1.0,
            0.0,
        ]  # directional
        self.lights_data[0 * LIGHT_SIZE + ATTENUATION] = [1.0, 0.0, 0.0, 0.0]
        # Light 1 - point light
        self.lights_data[1 * LIGHT_SIZE + AMBIENT] = [0.02, 0.02, 0.02, 1.0]
        self.lights_data[1 * LIGHT_SIZE + DIFFUSE] = [0.5, 0.5, 0.8, 1.0]
        self.lights_data[1 * LIGHT_SIZE + SPECULAR] = [0.5, 0.5, 0.5, 1.0]
        self.lights_data[1 * LIGHT_SIZE + POSITION] = [-5.0, 5.0, -10.0, 1.0]
        self.lights_data[1 * LIGHT_SIZE + ATTENUATION] = [1.0, 0.01, 0.001, 0.0]
        # Light 2 - another point light
        self.lights_data[2 * LIGHT_SIZE + AMBIENT] = [0.02, 0.02, 0.02, 1.0]
        self.lights_data[2 * LIGHT_SIZE + DIFFUSE] = [0.8, 0.5, 0.5, 1.0]
        self.lights_data[2 * LIGHT_SIZE + SPECULAR] = [0.5, 0.5, 0.5, 1.0]
        self.lights_data[2 * LIGHT_SIZE + POSITION] = [5.0, -5.0, -15.0, 1.0]
        self.lights_data[2 * LIGHT_SIZE + ATTENUATION] = [1.0, 0.01, 0.001, 0.0]

    def Render(self, mode=None):
        """Render the geometry for the scene."""
        if not mode.visible:
            return

        glUseProgram(self.shader)

        # The pass hands us the camera it is drawing with. There is no matrix
        # stack to ask in a core profile, and asking one would only tell us what
        # we had put there.
        modelview = mode.matrix
        projection = mode.projection
        mvp = dot(modelview, projection)
        # Normal matrix: the upper-left 3x3 of the model-view.
        normal_matrix = ascontiguousarray(modelview[:3, :3], dtype='f')

        # Set matrix uniforms (GL_FALSE = data is already in column-major format)
        glUniformMatrix4fv(self.mvp_loc, 1, GL_FALSE, mvp)
        glUniformMatrix4fv(self.mv_loc, 1, GL_FALSE, modelview)
        glUniformMatrix3fv(self.nm_loc, 1, GL_FALSE, normal_matrix)

        # Set material uniforms
        glUniform4f(self.ambient_loc, 0.1, 0.1, 0.1, 1.0)
        glUniform4f(self.diffuse_loc, 1.0, 1.0, 1.0, 1.0)
        glUniform4f(self.specular_loc, 0.4, 0.4, 0.4, 1.0)
        glUniform1f(self.shininess_loc, 0.5)
        glUniform4f(self.global_ambient_loc, 0.1, 0.1, 0.1, 1.0)

        # Set lights uniform
        glUniform4fv(self.lights_loc, LIGHT_COUNT * LIGHT_SIZE, self.lights_data)

        # Bind diffuse texture
        glActiveTexture(GL_TEXTURE0)
        self.texture_node.render(visible=True, mode=mode)
        glUniform1i(self.texture_loc, 0)

        # Bind offset texture buffer
        glActiveTexture(GL_TEXTURE1)
        glBindTexture(GL_TEXTURE_BUFFER, self.offset_texture)
        glUniform1i(self.offsets_loc, 1)

        # A vertex array object is where OpenGL keeps the description of which
        # buffer each attribute reads from; there is no such state outside one,
        # so a glVertexAttribPointer with nothing bound draws nothing.
        glBindVertexArray(self.vao)
        self.vertex_vbo.bind()
        stride = 8 * 4  # 8 floats per vertex (pos, tex, normal)

        glEnableVertexAttribArray(self.position_loc)
        glVertexAttribPointer(
            self.position_loc, 3, GL_FLOAT, GL_FALSE, stride, self.vertex_vbo
        )

        if self.texcoord_loc >= 0:
            glEnableVertexAttribArray(self.texcoord_loc)
            glVertexAttribPointer(
                self.texcoord_loc, 2, GL_FLOAT, GL_FALSE, stride, self.vertex_vbo + 12
            )

        if self.normal_loc >= 0:
            glEnableVertexAttribArray(self.normal_loc)
            glVertexAttribPointer(
                self.normal_loc, 3, GL_FLOAT, GL_FALSE, stride, self.vertex_vbo + 20
            )

        # Draw instanced geometry
        self.index_vbo.bind()
        glDrawElementsInstanced(
            GL_TRIANGLES,
            self.index_count,
            GL_UNSIGNED_SHORT,  # indices are uint16
            self.index_vbo,
            self.instance_count,
        )

        # Cleanup
        self.index_vbo.unbind()
        self.vertex_vbo.unbind()
        glDisableVertexAttribArray(self.position_loc)
        if self.texcoord_loc >= 0:
            glDisableVertexAttribArray(self.texcoord_loc)
        if self.normal_loc >= 0:
            glDisableVertexAttribArray(self.normal_loc)
        glBindVertexArray(0)

        glUseProgram(0)


if __name__ == "__main__":
    TestContext.ContextMainLoop()
