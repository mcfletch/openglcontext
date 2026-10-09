"""KHR_materials_volume_scatter: light scattered beneath a surface, blurred across it

Before the opaque shapes are drawn, the shapes whose material has a
`VolumeScatterMaterialExtension` are drawn into :class:`ScatterBuffer`: the
light their diffuse transmission lobes take in, before it spreads, and the
view-space depth of each fragment. The PBR program then reads that buffer
back around each of their fragments, weighting the samples by the Burley
diffusion profile over the distance between the points, and adds the result
as subsurface light. The profile's reach is the volume's
`attenuationDistance` times the material's `multiscatterColor`, per channel.

:func:`scatter_samples` is the fixed set of sample offsets the program reads
at, and :func:`has_volume_scatter` says which materials are drawn so. The
sample set and the profile follow X_ITE 16.4.3's (`ScatterSamples.js`, MIT
licence, copyright Holger Seelig and contributors), which in turn follows
Blender's Burley profile.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Optional

import numpy as np
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE, GL_COLOR_ATTACHMENT0, GL_COLOR_BUFFER_BIT, GL_DEPTH_ATTACHMENT,
    GL_DEPTH_BUFFER_BIT, GL_DEPTH_COMPONENT24, GL_FLOAT, GL_FRAMEBUFFER,
    GL_FRAMEBUFFER_COMPLETE, GL_NEAREST, GL_RENDERBUFFER, GL_RGBA, GL_RGBA32F,
    GL_TEXTURE0, GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_TEXTURE_MIN_FILTER,
    GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, glActiveTexture,
    glBindRenderbuffer, glBindTexture, glCheckFramebufferStatus, glClear, glClearColor,
    glDeleteFramebuffers, glDeleteRenderbuffers, glDeleteTextures, glDrawBuffers,
    glFramebufferRenderbuffer, glFramebufferTexture2D, glGenFramebuffers,
    glGenRenderbuffers, glGenTextures, glRenderbufferStorage, glTexImage2D,
    glTexParameteri,
)

from OpenGLContext.passes import glstate
from OpenGLContext.scenegraph import materialextensions

#: The texture unit the PBR program reads the scatter buffer from: past the
#: units the texture layers and projectors take (pbrpass).
SCATTER_UNIT = 37
#: How many samples of the buffer each fragment reads.
SCATTER_SAMPLES_COUNT = 55
#: The cumulative probability the profile's sampling covers.
_COVERED = 0.9963790093708328


def _burley_setup(radius: float, albedo: float) -> float:
    s = 1.9 - albedo + 3.5 * (albedo - 0.8) ** 2
    return 0.25 / math.pi * radius / s


def _burley_eval(d: float, r: float) -> float:
    if r >= 16.0 * d:
        return 0.0
    third = math.exp(-r / (3.0 * d))
    return (third ** 3 + third) / (8.0 * math.pi * d)


def _burley_sample(d: float, x: float) -> float:
    """The radius at cumulative probability `x`, by Newton's method on the CDF"""
    x *= _COVERED
    r = math.exp(x * x * 2.4) - 1.0 if x <= 0.9 else 15.0
    for _step in range(10):
        third = math.exp(-r / 3.0)
        f = 1.0 - 0.25 * third ** 3 - 0.75 * third - x
        slope = 0.25 * third ** 3 + 0.25 * third
        if abs(f) < 1e-6 or slope == 0.0:
            break
        r = max(r - f / slope, 0.0)
    return r * d


@lru_cache(maxsize=1)
def scatter_samples() -> "tuple[np.ndarray, float]":
    """The (angle, radius, 1/pdf) of each sample, and the least radius among them

    The samples lie on a golden-angle spiral, their radii spaced evenly in the
    profile's cumulative probability for a unit radius and white albedo.
    """
    d = _burley_setup(1.0, 1.0)
    golden = math.pi * (3.0 - math.sqrt(5.0))
    rows = []
    least = 1.0
    for index in range(SCATTER_SAMPLES_COUNT):
        angle = golden * index + math.pi
        radius = _burley_sample(d, (0.5 + index) / SCATTER_SAMPLES_COUNT)
        least = min(least, radius)
        rows.append((angle, radius, _COVERED / _burley_eval(d, radius)))
    return np.asarray(rows, np.float32), max(least, 0.00001)


def has_volume_scatter(material: Any) -> bool:
    """Whether `material` has a VolumeScatterMaterialExtension, and so is drawn with scatter"""
    from vrml.x3d import xite  # noqa: PLC0415 kept with its use
    return materialextensions.extension_of(material, xite.VolumeScatterMaterialExtension) is not None


class ScatterBuffer:
    """The light the scattering shapes take in, and their depth, for one view size

    A float colour texture holding the light in its RGB and the view-space
    distance in front of the eye in its A, with a depth buffer of its own.
    """

    UNIT = SCATTER_UNIT

    def __init__(self) -> None:
        self.texture: Optional[int] = None
        self.framebuffer: Optional[int] = None
        self.depth: Optional[int] = None
        self.size = (0, 0)

    def ensure_size(self, width: int, height: int) -> bool:
        """Allocate for a view `width` by `height`; False where the driver refuses"""
        size = (max(1, int(width)), max(1, int(height)))
        if self.framebuffer is not None and size == self.size:
            return True
        self.release()
        self.size = size
        self.texture = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, self.texture)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA32F, size[0], size[1], 0, GL_RGBA, GL_FLOAT, None)
        for name, value in ((GL_TEXTURE_MIN_FILTER, GL_NEAREST), (GL_TEXTURE_MAG_FILTER, GL_NEAREST),
                            (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                            (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)):
            glTexParameteri(GL_TEXTURE_2D, name, value)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.depth = int(glGenRenderbuffers(1))
        glBindRenderbuffer(GL_RENDERBUFFER, self.depth)
        glRenderbufferStorage(GL_RENDERBUFFER, GL_DEPTH_COMPONENT24, size[0], size[1])
        glBindRenderbuffer(GL_RENDERBUFFER, 0)
        self.framebuffer = int(glGenFramebuffers(1))
        with glstate.bound_framebuffer(self.framebuffer):
            glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                                   self.texture, 0)
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_RENDERBUFFER,
                                      self.depth)
            complete = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
        return bool(complete)

    def begin(self) -> None:
        """Clear the buffer, which the caller has bound, and draw into its colour"""
        glDrawBuffers(1, np.array([GL_COLOR_ATTACHMENT0], np.uint32))
        glClearColor(0.0, 0.0, 0.0, 0.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    def bind(self) -> None:
        """Put the buffer's texture on :data:`SCATTER_UNIT`"""
        glActiveTexture(GL_TEXTURE0 + self.UNIT)
        glBindTexture(GL_TEXTURE_2D, self.texture or 0)
        glActiveTexture(GL_TEXTURE0)

    def release(self) -> None:
        """Delete the buffer's GL objects"""
        if self.framebuffer is not None:
            glDeleteFramebuffers(1, np.array([self.framebuffer], np.uint32))
        if self.depth is not None:
            glDeleteRenderbuffers(1, np.array([self.depth], np.uint32))
        if self.texture is not None:
            glDeleteTextures(1, np.array([self.texture], np.uint32))
        self.framebuffer = self.depth = self.texture = None
        self.size = (0, 0)
