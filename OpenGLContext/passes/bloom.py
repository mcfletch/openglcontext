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
from dataclasses import dataclass
from typing import Any, Optional, Tuple

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
    # int(), because glGenTextures answers a numpy scalar for a count of one.
    t = int(glGenTextures(1))
    glBindTexture(GL_TEXTURE_2D, t)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA16F, w, h, 0, GL_RGBA, GL_FLOAT, None)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, filt)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, filt)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glBindTexture(GL_TEXTURE_2D, 0)
    return t


@dataclass(frozen=True)
class _Chain:
    """The vertex array and the three programs a bloom draws with.

    Made once and kept: nothing about them depends on the window size.
    """

    vao: int
    bright: int
    blur: int
    composite: int


@dataclass(frozen=True)
class _Targets:
    """The framebuffers and textures a frame of one size is drawn into.

    One record rather than seven attributes because they are made together and
    released together, and a half-built set is not a thing a frame can be drawn
    with: a scene texture that outlived the size it was made at would be drawn
    into at the wrong one.
    """

    size: Tuple[int, int]
    bloom_size: Tuple[int, int]
    scene_fbo: int
    scene_tex: int
    depth_rb: int
    ping_fbo: Tuple[int, int]
    ping_tex: Tuple[int, int]


class BloomPass(object):
    """Per-context HDR scene target + bloom chain (created lazily, resized on demand)."""

    THRESHOLD = 1.0        # luminance above which pixels bloom (linear; emissive>1 blooms)
    STRENGTH = 0.6         # bloom add-back weight
    BLUR_ITERATIONS = 5    # ping-pong passes (each = one H + one V blur)

    def __init__(self) -> None:
        self._prev_fbo: int = 0
        self._chain: Optional[_Chain] = None
        self._targets: Optional[_Targets] = None

    @property
    def size(self) -> Optional[Tuple[int, int]]:
        """What the scene target is sized for, or None while there is none."""
        return self._targets.size if self._targets else None

    @property
    def bloom_size(self) -> Optional[Tuple[int, int]]:
        """The half-resolution size the blur works at."""
        return self._targets.bloom_size if self._targets else None

    # -- lifecycle --------------------------------------------------------
    def _ensure(self, w: int, h: int) -> Tuple[_Chain, _Targets]:
        """The chain and the targets for a frame this size, made if need be."""
        if self._chain is None:
            self._chain = _Chain(
                vao=glGenVertexArrays(1),
                bright=_compile(_FS_VERT, _BRIGHT_FRAG),
                blur=_compile(_FS_VERT, _BLUR_FRAG),
                composite=_compile(_FS_VERT, _COMPOSITE_FRAG),
            )
        if self._targets is not None and self._targets.size == (w, h):
            return self._chain, self._targets
        self._release_targets()
        scene_tex = _color_tex(w, h)
        scene_fbo = glGenFramebuffers(1)
        glBindFramebuffer(GL_FRAMEBUFFER, scene_fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                               scene_tex, 0)
        depth_rb = glGenRenderbuffers(1)
        glBindRenderbuffer(GL_RENDERBUFFER, depth_rb)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, w, h)
        glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER,
                                  depth_rb)
        bw, bh = max(1, w // 2), max(1, h // 2)     # half-res bloom
        ping_tex, ping_fbo = [], []
        for _index in range(2):
            ping_tex.append(_color_tex(bw, bh))
            ping_fbo.append(glGenFramebuffers(1))
            glBindFramebuffer(GL_FRAMEBUFFER, ping_fbo[-1])
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                                   ping_tex[-1], 0)
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        self._targets = _Targets(
            size=(w, h), bloom_size=(bw, bh),
            scene_fbo=scene_fbo, scene_tex=scene_tex, depth_rb=depth_rb,
            ping_fbo=(ping_fbo[0], ping_fbo[1]),
            ping_tex=(ping_tex[0], ping_tex[1]),
        )
        return self._chain, self._targets

    def begin(self, w: int, h: int) -> bool:
        """Bind the HDR scene target and clear it; returns True if bloom is active."""
        _chain, targets = self._ensure(w, h)
        self._prev_fbo = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
        glBindFramebuffer(GL_FRAMEBUFFER, targets.scene_fbo)
        glViewport(0, 0, w, h)
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        return True

    def composite(self) -> None:
        """Bright-pass + blur the HDR scene and composite it to the previous target.

        Does nothing where :meth:`begin` has not run: there is no scene to
        composite, and every name below would be missing.
        """
        chain, targets = self._chain, self._targets
        if chain is None or targets is None:
            return
        w, h = targets.size
        bw, bh = targets.bloom_size
        glDisable(GL_DEPTH_TEST)
        glDisable(GL_BLEND)
        glBindVertexArray(chain.vao)

        # 1. bright pass -> ping[0] (half res)
        glBindFramebuffer(GL_FRAMEBUFFER, targets.ping_fbo[0])
        glViewport(0, 0, bw, bh)
        glUseProgram(chain.bright)
        self._bind_tex(chain.bright, 'scene', targets.scene_tex, 0)
        glUniform1f(glGetUniformLocation(chain.bright, 'threshold'), self.THRESHOLD)
        glDrawArrays(GL_TRIANGLES, 0, 3)

        # 2. separable Gaussian blur, ping-ponging between the two half-res targets
        glUseProgram(chain.blur)
        src, dst = 0, 1
        for i in range(self.BLUR_ITERATIONS * 2):
            horizontal = (i % 2 == 0)
            glBindFramebuffer(GL_FRAMEBUFFER, targets.ping_fbo[dst])
            glViewport(0, 0, bw, bh)
            self._bind_tex(chain.blur, 'image', targets.ping_tex[src], 0)
            dx = (1.0 / bw) if horizontal else 0.0
            dy = 0.0 if horizontal else (1.0 / bh)
            glUniform2f(glGetUniformLocation(chain.blur, 'direction'), dx, dy)
            glDrawArrays(GL_TRIANGLES, 0, 3)
            src, dst = dst, src

        # 3. composite scene + bloom -> the target that was bound before begin()
        glBindFramebuffer(GL_FRAMEBUFFER, self._prev_fbo)
        glViewport(0, 0, w, h)
        glUseProgram(chain.composite)
        self._bind_tex(chain.composite, 'scene', targets.scene_tex, 0)
        self._bind_tex(chain.composite, 'bloom', targets.ping_tex[src], 1)
        glUniform1f(glGetUniformLocation(chain.composite, 'strength'), self.STRENGTH)
        glDrawArrays(GL_TRIANGLES, 0, 3)

        glBindVertexArray(0)
        glUseProgram(0)
        glActiveTexture(GL_TEXTURE0)
        glEnable(GL_DEPTH_TEST)

    @staticmethod
    def _bind_tex(prog: int, name: str, tex: int, unit: int) -> None:
        glActiveTexture(GL_TEXTURE0 + unit)
        glBindTexture(GL_TEXTURE_2D, tex)
        loc = glGetUniformLocation(prog, name)
        if loc >= 0:
            glUniform1i(loc, unit)

    # -- cleanup ----------------------------------------------------------
    def _release_targets(self) -> None:
        """Give the size-dependent objects back, whatever the driver says.

        A delete that fails leaks one name; stopping here would leave the pass
        holding names it has already half-freed, which is worse.
        """
        targets, self._targets = self._targets, None
        if targets is None:
            return
        for fbo in (targets.scene_fbo,) + targets.ping_fbo:
            try:
                glDeleteFramebuffers(1, [fbo])
            except Exception:
                pass
        for tex in (targets.scene_tex,) + targets.ping_tex:
            try:
                glDeleteTextures([tex])
            except Exception:
                pass
        try:
            glDeleteRenderbuffers(1, [targets.depth_rb])
        except Exception:
            pass
