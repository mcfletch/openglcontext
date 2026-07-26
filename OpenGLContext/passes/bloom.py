"""Optional HDR bloom post-process (``OPENGLCONTEXT_BLOOM``).

Off by default: the scene renders straight to the framebuffer, tone-mapped in the
geometry shaders exactly as before, so the visual-regression suite is unaffected.
When enabled, the pass instead:

  1. renders the scene into a linear ``RGBA16F`` HDR target (the PBR shader emits
     linear HDR via its ``hdrOutput`` uniform, so >1 emissive survives),
  2. extracts the bright pixels, blurs them (separable Gaussian, ping-pong),
  3. composites ``toneMap(scene + strength*bloom)`` back to the framebuffer.

This is what makes ``KHR_materials_emissive_strength`` read as a glow whose spread
grows with strength (EmissiveStrengthTest), instead of clamping flat to white.
"""
from __future__ import annotations

import os
from typing import Any, List, Optional, Tuple

from OpenGL.GL import (
    GL_TRIANGLES, GL_TEXTURE_2D, GL_TEXTURE0, GL_RGBA16F, GL_RGBA, GL_FLOAT,
    GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_FRAMEBUFFER_BINDING,
    GL_CLAMP_TO_EDGE, GL_LINEAR,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_WRAP_S,
    GL_TEXTURE_WRAP_T, GL_DEPTH_TEST, GL_BLEND,
    GL_VERTEX_SHADER, GL_FRAGMENT_SHADER, GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT,
    GL_DEPTH_COMPONENT24, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER,
    glGenFramebuffers, glBindFramebuffer, glFramebufferTexture2D, glDeleteFramebuffers,
    glGenTextures, glBindTexture, glTexImage2D, glTexParameteri, glDeleteTextures,
    glGenRenderbuffers, glBindRenderbuffer, glRenderbufferStorage,
    glFramebufferRenderbuffer, glDeleteRenderbuffers,
    glGenVertexArrays, glBindVertexArray,
    glViewport, glClear, glClearColor, glUseProgram,
    glDrawArrays, glActiveTexture, glEnable, glDisable, glGetIntegerv,
    glGetUniformLocation, glUniform1i, glUniform1f, glUniform2f,
)
from OpenGL.GL import shaders as GL_shaders


def bloom_enabled(source: Any = None) -> bool:
    """Whether the bloom post-process runs (ContextDefinition.bloom).

    ``source`` is the render pass asking, from which the context definition is
    found; without one the environment default stands, which is what a bare
    unit test gets.
    """
    from OpenGLContext import renderoptions
    default = renderoptions.env_flag('OPENGLCONTEXT_BLOOM', False)
    if source is None:
        return default
    return renderoptions.flag(source, 'bloom', default)


_FS_VERT = """#version 330 core
out vec2 uv;
void main(){
    // fullscreen triangle from gl_VertexID (no VBO)
    vec2 p = vec2((gl_VertexID << 1) & 2, gl_VertexID & 2);
    uv = p;
    gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
}"""

_BRIGHT_FRAG = """#version 330 core
in vec2 uv; out vec4 frag;
uniform sampler2D scene; uniform float threshold;
void main(){
    vec3 c = texture(scene, uv).rgb;
    float l = dot(c, vec3(0.2126, 0.7152, 0.0722));
    // soft knee above the threshold so the bloom ramps in smoothly
    float k = clamp((l - threshold) / max(threshold, 1e-3), 0.0, 1.0);
    frag = vec4(c * k, 1.0);
}"""

_BLUR_FRAG = """#version 330 core
in vec2 uv; out vec4 frag;
uniform sampler2D image; uniform vec2 direction;   // texel-sized step along one axis
void main(){
    float w[5] = float[](0.227027, 0.194594, 0.121621, 0.054054, 0.016216);
    vec3 c = texture(image, uv).rgb * w[0];
    for(int i = 1; i < 5; ++i){
        c += texture(image, uv + direction * float(i)).rgb * w[i];
        c += texture(image, uv - direction * float(i)).rgb * w[i];
    }
    frag = vec4(c, 1.0);
}"""

_COMPOSITE_FRAG = """#version 330 core
in vec2 uv; out vec4 frag;
uniform sampler2D scene; uniform sampler2D bloom; uniform float strength;
vec3 aces(vec3 x){
    const float a=2.51, b=0.03, c=2.43, d=0.59, e=0.14;
    return clamp((x*(a*x+b))/(x*(c*x+d)+e), 0.0, 1.0);
}
vec3 toSRGB(vec3 c){
    return mix(1.055*pow(max(c,0.0), vec3(1.0/2.4))-0.055, c*12.92, step(c, vec3(0.0031308)));
}
void main(){
    vec3 hdr = texture(scene, uv).rgb + strength * texture(bloom, uv).rgb;
    frag = vec4(toSRGB(aces(hdr)), 1.0);
}"""


def _compile(vert: str, frag: str) -> Any:
    return GL_shaders.compileProgram(
        GL_shaders.compileShader(vert, GL_VERTEX_SHADER),
        GL_shaders.compileShader(frag, GL_FRAGMENT_SHADER), validate=False)


def _color_tex(w: int, h: int, filt: int = GL_LINEAR) -> int:
    t = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, t)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, None)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filt)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filt)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glBindTexture(GL_TEXTURE_2D, 0)
    return t


class BloomPass(object):
    """Per-context HDR scene target + bloom chain (created lazily, resized on demand)."""

    THRESHOLD = 1.0        # luminance above which pixels bloom (linear; emissive>1 blooms)
    STRENGTH = 0.6         # bloom add-back weight
    BLUR_ITERATIONS = 5    # ping-pong passes (each = one H + one V blur)

    def __init__(self) -> None:
        self._size: Optional[Tuple[int, int]] = None
        self._bloom_size: Optional[Tuple[int, int]] = None
        self._prev_fbo: int = 0
        self._scene_fbo: Optional[int] = None
        self._scene_tex: Optional[int] = None
        self._depth_rb: Optional[int] = None
        self._ping_fbo: List[Optional[int]] = [None, None]
        self._ping_tex: List[Optional[int]] = [None, None]
        self._vao: Optional[int] = None
        self._prog_bright: Optional[int] = None
        self._prog_blur: Optional[int] = None
        self._prog_comp: Optional[int] = None

    # -- lifecycle --------------------------------------------------------
    def _ensure(self, w: int, h: int) -> None:
        if self._vao is None:
            self._vao = glGenVertexArrays(1)
            self._prog_bright = _compile(_FS_VERT, _BRIGHT_FRAG)
            self._prog_blur = _compile(_FS_VERT, _BLUR_FRAG)
            self._prog_comp = _compile(_FS_VERT, _COMPOSITE_FRAG)
        if self._size == (w, h):
            return
        self._release_targets()
        self._scene_tex = _color_tex(w, h)
        self._scene_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, self._scene_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                               self._scene_tex, 0)
        self._depth_rb = glGenRenderbuffers(1)
        glBindRenderbuffer(GL_RENDERBUFFER, self._depth_rb)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, w, h)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER,
                                  self._depth_rb)
        bw, bh = max(1, w // 2), max(1, h // 2)     # half-res bloom
        for i in range(2):
            self._ping_tex[i] = _color_tex(bw, bh)
            self._ping_fbo[i] = glGenFramebuffers(1)
            glBindFramebuffer(GL_FRAMEBUFFER, self._ping_fbo[i])
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                                   self._ping_tex[i], 0)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        self._size = (w, h)
        self._bloom_size = (bw, bh)

    def begin(self, w: int, h: int) -> bool:
        """Bind the HDR scene target and clear it; returns True if bloom is active."""
        self._ensure(w, h)
        self._prev_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
        glBindFramebuffer(GL_FRAMEBUFFER, self._scene_fbo)
        glViewport(0, 0, w, h)
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        return True

    def composite(self) -> None:
        """Bright-pass + blur the HDR scene and composite it to the previous target."""
        assert self._size is not None and self._bloom_size is not None
        w, h = self._size
        bw, bh = self._bloom_size
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        glBindVertexArray(self._vao)

        # 1. bright pass -> ping[0] (half res)
        glBindFramebuffer(GL_FRAMEBUFFER, self._ping_fbo[0])
        glViewport(0, 0, bw, bh)
        glUseProgram(self._prog_bright)
        self._bind_tex(self._prog_bright, 'scene', self._scene_tex, 0)
        glUniform1f(glGetUniformLocation(self._prog_bright, 'threshold'), self.THRESHOLD)
        glDrawArrays(GL_TRIANGLES, 0, 3)

        # 2. separable Gaussian blur, ping-ponging between the two half-res targets
        glUseProgram(self._prog_blur)
        src, dst = 0, 1
        for i in range(self.BLUR_ITERATIONS * 2):
            horizontal = (i % 2 == 0)
            glBindFramebuffer(GL_FRAMEBUFFER, self._ping_fbo[dst])
            glViewport(0, 0, bw, bh)
            self._bind_tex(self._prog_blur, 'image', self._ping_tex[src], 0)
            dx = (1.0 / bw) if horizontal else 0.0
            dy = 0.0 if horizontal else (1.0 / bh)
            glUniform2f(glGetUniformLocation(self._prog_blur, 'direction'), dx, dy)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            src, dst = dst, src

        # 3. composite scene + bloom -> the target that was bound before begin()
        glBindFramebuffer(GL_FRAMEBUFFER, self._prev_fbo)
        glViewport(0, 0, w, h)
        glUseProgram(self._prog_comp)
        self._bind_tex(self._prog_comp, 'scene', self._scene_tex, 0)
        self._bind_tex(self._prog_comp, 'bloom', self._ping_tex[src], 1)
        glUniform1f(glGetUniformLocation(self._prog_comp, 'strength'), self.STRENGTH)
        glDrawArrays(GL_TRIANGLES, 0, 3)

        glBindVertexArray(0)
        glUseProgram(0)
        glActiveTexture(GL_TEXTURE0)
        glEnable(GL_DEPTH_TEST)

    @staticmethod
    def _bind_tex(prog: Any, name: str, tex: Optional[int], unit: int) -> None:
        glActiveTexture(GL_TEXTURE0 + unit)
        glBindTexture(GL_TEXTURE_2D, tex)
        loc = glGetUniformLocation(prog, name)
        if loc >= 0:
            glUniform1i(loc, unit)

    # -- cleanup ----------------------------------------------------------
    def _release_targets(self) -> None:
        for fbo in [self._scene_fbo] + list(self._ping_fbo):
            if fbo:
                try:
                    glDeleteFramebuffers(1, [fbo])
                except Exception:
                    pass
        for tex in [self._scene_tex] + list(self._ping_tex):
            if tex:
                try:
                    glDeleteTextures([tex])
                except Exception:
                    pass
        if self._depth_rb:
            try:
                glDeleteRenderbuffers(1, [self._depth_rb])
            except Exception:
                pass
        self._scene_fbo = self._scene_tex = self._depth_rb = None
        self._ping_fbo = [None, None]
        self._ping_tex = [None, None]
