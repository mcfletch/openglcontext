#! /usr/bin/env python
# import OpenGL
# OpenGL.FULL_LOGGING=True
from shader_11 import TestContext as BaseContext
from OpenGL.GL import *
from OpenGLContext.arrays import *
from OpenGLContext.scenegraph.basenodes import *
from OpenGL.GL.ARB.draw_instanced import *
from OpenGL.GL.ARB.texture_buffer_object import *
from numpy import random
import weakref
import logging

log = logging.getLogger(__name__)


def cleaner(locks, deleter):
    for (start, stop), sync in locks:
        deleter(sync)


class BufferLocks(object):
    """Holds fences for transfer-complete on blocks

    Note: the un-accelerated version of this is likely to cause more
    overhead than the whole AZBO technique is supposed to save.
    """

    _cleanups_ = []

    def __init__(self, client=False):
        self.locks = []
        self.client = False
        self.__class__._cleanups_.append(
            weakref.ref(self, cleaner(self.locks, glDeleteSync))
        )

    def lock(self, start, stop):
        """Create a lock for the given range"""
        sync = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0)
        self.locks.append(((start, stop), sync))

    def wait(self, start, stop):
        """Note: this is *not* thread safe, but it should only ever be called by the rendering thread"""
        to_delete = []
        for i, ((ostart, ostop), sync) in enumerate(self.locks):
            if start <= ostop and stop > ostart:
                self._wait(sync)
                to_delete.append(i)
        for i in to_delete[::-1]:
            del self.locks[i]

    def _wait(self, sync):
        try:
            if self.client:
                # did we already complete?
                # PyOpenGL will raise errors if they occur here
                if glClientWaitSync(sync, 0, 0) == GL_TIMEOUT_EXPIRED:
                    # okay, so we are stalling, that's not good, but
                    # flush commands and actually do a wait...
                    print("Stalled")
                    if (
                        glClientWaitSync(sync, GL_SYNC_FLUSH_COMMANDS_BIT, 100000000)
                        == GL_TIMEOUT_EXPIRED
                    ):
                        raise RuntimeError(
                            "Stall of over 1/10th of a second waiting for sync"
                        )
                    return sync
        finally:
            glDeleteSync(sync)


class MappedBuffer(object):
    """Holds a persistently-mapped buffer"""


class TestContext(BaseContext):
    def OnInit(self):
        """Initialize the context"""
        self.lights = self.createLights()
        self.LIGHTS = array([self.lightAsArray(l) for l in self.lights], "f")
        self.shader_constants["LIGHT_COUNT"] = len(self.lights)
        light_preCalc = GLSLImport(url="_shader_tut_lightprecalc.vert")
        phong_preCalc = GLSLImport(url="res://phongprecalc_vert")
        phong_weightCalc = GLSLImport(url="res://phongweights_frag")
        lightConst = GLSLImport(
            source="\n".join(
                [
                    "const int %s = %s;" % (k, v)
                    for k, v in self.shader_constants.items()
                ]
            )
            + """
            uniform vec4 lights[ LIGHT_COUNT*LIGHT_SIZE ];

            varying vec3 EC_Light_half[LIGHT_COUNT];
            varying vec3 EC_Light_location[LIGHT_COUNT];
            varying float Light_distance[LIGHT_COUNT];

            varying vec3 baseNormal;
            varying vec2 Vertex_texture_coordinate_var;
            """
        )
        hardlimit = glGetIntegerv(GL_MAX_TEXTURE_BUFFER_SIZE_ARB)
        count = min((15000, hardlimit // 16))
        scale = [40, 40, 40, 0]
        offset = [-20, -20, -40, 1]
        self.offset_array = (
            # we require RGBA to be compatible with < OpenGL 4.x
            random.random(size=(count, 4)) * scale + offset
        ).astype("f")
        TEXTURE_BUFFER_UNIFORM = TextureBufferUniform(
            name="offsets_table",
            format="RGBA32F",
            value=ShaderBuffer(
                usage="STATIC_DRAW",
                type="TEXTURE",
                buffer=self.offset_array,
            ),
        )
        VERTEX_SHADER = """
        attribute vec3 Vertex_position;
        attribute vec3 Vertex_normal;
        attribute vec2 Vertex_texture_coordinate;
        uniform samplerBuffer offsets_table;
        void main() {
            vec3 offset = texelFetch( offsets_table, gl_InstanceIDARB ).xyz;
            vec3 final_position = Vertex_position + offset;
            gl_Position = gl_ModelViewProjectionMatrix * vec4(
                final_position, 1.0
            );
            baseNormal = gl_NormalMatrix * normalize(Vertex_normal);
            light_preCalc(final_position);
            Vertex_texture_coordinate_var = Vertex_texture_coordinate;
        }"""
        self.glslObject = GLSLObject(
            uniforms=[
                FloatUniform1f(name="material.shininess", value=0.5),
                FloatUniform4f(name="material.ambient", value=(0.1, 0.1, 0.1, 1.0)),
                FloatUniform4f(name="material.diffuse", value=(1.0, 1.0, 1.0, 1.0)),
                FloatUniform4f(name="material.specular", value=(0.4, 0.4, 0.4, 1.0)),
                FloatUniform4f(name="Global_ambient", value=(0.1, 0.1, 0.1, 1.0)),
                FloatUniform4f(name="lights"),
            ],
            textures=[
                TextureUniform(
                    name="diffuse_texture",
                    value=ImageTexture(
                        url="marbleface.jpeg",
                    ),
                ),
                TEXTURE_BUFFER_UNIFORM,
            ],
            shaders=[
                GLSLShader(
                    imports=[
                        lightConst,
                        phong_preCalc,
                        light_preCalc,
                    ],
                    source=[VERTEX_SHADER],
                    type="VERTEX",
                ),
                GLSLShader(
                    imports=[
                        lightConst,
                        phong_weightCalc,
                    ],
                    source=[
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
                    type="FRAGMENT",
                ),
            ],
        )
        coords, indices = Sphere(radius=0.25, phi=pi / 8.0).compileArrays()
        self.coords = ShaderBuffer(buffer=coords)
        self.indices = ShaderIndexBuffer(buffer=indices)
        self.count = len(indices)
        stride = coords[0].nbytes
        self.attributes = [
            ShaderAttribute(
                name="Vertex_position",
                offset=0,
                stride=stride,
                buffer=self.coords,
                isCoord=True,
            ),
            ShaderAttribute(
                name="Vertex_texture_coordinate",
                offset=4 * 3,
                stride=stride,
                buffer=self.coords,
                size=2,
                isCoord=False,
            ),
            ShaderAttribute(
                name="Vertex_normal",
                offset=4 * 5,
                stride=stride,
                buffer=self.coords,
                isCoord=False,
            ),
        ]
        self.appearance = Appearance(
            material=Material(
                diffuseColor=(1, 1, 1),
                ambientIntensity=0.1,
                shininess=0.5,
            ),
        )
        self.buffer_locks = BufferLocks()
        self.offset = 0

    def Render(self, mode=None):
        """Render the geometry for the scene."""
        if not mode.visible:
            return
        if not self.glslObject.compile(mode):
            log.warning("glslobject failed to compile")
            return
        self.buffer_locks.lock(self.offset, 50)
        self.offset += 50
        for i, light in enumerate(self.lights):
            self.LIGHTS[i] = self.lightAsArray(light)
        self.glslObject.getVariable("lights").value = self.LIGHTS
        for key, value in self.materialFromAppearance(self.appearance, mode).items():
            self.glslObject.getVariable(key).value = value
        token = self.glslObject.render(mode)
        tokens = []
        vbo = self.indices.bind(mode)
        try:
            for attribute in self.attributes:
                token = attribute.render(self.glslObject, mode)
                if token:
                    tokens.append((attribute, token))
            glDrawElementsInstanced(
                GL_TRIANGLES,
                self.count,
                GL_UNSIGNED_INT,
                vbo,
                len(self.offset_array),  # number of instances to draw...
            )
            self.buffer_locks.wait(10, 240)
        finally:
            for attribute, token in tokens:
                attribute.renderPost(self.glslObject, mode, token)
            self.glslObject.renderPost(token, mode)
            vbo.unbind()


if __name__ == "__main__":
    TestContext.ContextMainLoop()
