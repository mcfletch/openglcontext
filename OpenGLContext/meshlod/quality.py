"""What a level of detail looks like, measured by rendering it.

A level's geometric error is a length, and a length decides nothing on its own:
a millimetre is invisible on a cliff and ruinous on a face. The question a
renderer has is whether swapping a level in **changes the picture**, and that is
answered by drawing both and comparing.

:func:`object_pop` is the measure: the fraction of the object's own pixels that
change. Of the object's own, not of the frame -- a whole-frame fraction says a
far-away object is perfect no matter what happened to it, because it covers
four pixels either way.

:func:`safe_distance` turns a sweep of those numbers into the thing a renderer
actually needs: the closest distance at which a level may be used without the
change being visible.

The metrics take images and return numbers, so they are tested without a window.
:class:`LODProbe` is the part that needs GL, and is a thin shell around them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

__all__ = [
    "CHANNEL_DELTA",
    "object_pop",
    "silhouette",
    "safe_distance",
    "LODProbe",
    "LevelReport",
    "measure_chain",
]

#: How far one channel must move for a pixel to count as changed, out of 255.
#: Below this is dithering and the last bit of interpolation, which no viewer
#: sees; the threshold keeps the measure from reporting shader noise as a pop.
CHANNEL_DELTA = 12


def silhouette(image: Any, background: int = 0) -> Any:
    """Which pixels the object covers, as a boolean mask."""
    return np.asarray(image).max(axis=2) > background


def object_pop(before: Any, after: Any, channel_delta: int = CHANNEL_DELTA) -> float:
    """Fraction of the object's pixels that change between two renders.

    The denominator is every pixel either render covers, so geometry that
    *appears* counts as much as geometry that vanishes. With neither render
    covering anything the answer is zero: nothing is on screen to pop.
    """
    before = np.asarray(before, dtype=np.int16)
    after = np.asarray(after, dtype=np.int16)
    covered = silhouette(before) | silhouette(after)
    if not np.any(covered):
        return 0.0
    changed = np.abs(before - after).max(axis=2) > channel_delta
    return float(np.count_nonzero(changed & covered) / np.count_nonzero(covered))


def pop_breakdown(
    before: Any, after: Any, channel_delta: int = CHANNEL_DELTA
) -> tuple[float, float]:
    """Split :func:`object_pop` into what moved and what merely shaded differently.

    Returns ``(silhouette, shading)``, both as shares of the object's pixels and
    summing to the whole pop. A pixel one render covers and the other does not is
    charged to the silhouette; a pixel both cover but disagree on is charged to
    the shading.

    The two want different remedies. A silhouette that changed means the level
    has lost shape and needs triangles. Shading that changed at the same
    silhouette means its normals are different -- which on a coarser mesh they
    inevitably are, and which is what a baked normal map, or a less mirror-like
    material, absorbs. Reporting one number for both hides which is happening.
    """
    before = np.asarray(before, dtype=np.int16)
    after = np.asarray(after, dtype=np.int16)
    here, there = silhouette(before), silhouette(after)
    covered = here | there
    total = np.count_nonzero(covered)
    if not total:
        return 0.0, 0.0
    outline = here ^ there
    changed = np.abs(before - after).max(axis=2) > channel_delta
    return (
        float(np.count_nonzero(outline) / total),
        float(np.count_nonzero(changed & ~outline & covered) / total),
    )


def safe_distance(distances: Sequence[float], pops: Sequence[float], budget: float) -> float:
    """The distance beyond which the level's pop stays within ``budget``.

    ``distances`` must be increasing and ``pops`` their measurements. Read from
    the **far end inwards**, because a sweep is not monotone: close enough and
    the camera is inside the object, nothing is on screen, and both renders
    agree on an empty frame. Taken from the near end that reads as a pass, and
    would report the coarsest level as usable from touching distance. The answer
    wanted is the point past which the level is always good enough.

    The crossing is interpolated between the two samples that straddle it rather
    than snapped to one, so the answer does not depend on how finely the sweep
    was taken. ``inf`` means no distance is far enough.
    """
    span = np.asarray(distances, dtype="d")
    measured = np.asarray(pops, dtype="d")
    if not len(span) or measured[-1] > budget:
        return float("inf")
    # The first sample, walking in from the far end, that breaks the budget.
    over = np.flatnonzero(measured > budget)
    if not len(over):
        return float(span[0])
    breaks = int(over[-1])
    low, high = span[breaks], span[breaks + 1]
    lower, upper = measured[breaks], measured[breaks + 1]
    if lower == upper:
        return float(high)
    return float(low + (high - low) * (lower - budget) / (lower - upper))


@dataclass
class LevelReport:
    """What one level of a chain measured."""

    level: int
    triangle_count: int
    error: float
    pops: list[float]
    #: The same measurements split into outline and shading, per distance.
    outlines: list[float]
    shadings: list[float]
    safe_at: float
    #: Where the level would be safe if only its outline were judged -- the
    #: distance a normal map, or a less mirror-like material, would buy back.
    safe_at_outline: float

    @property
    def reduction(self) -> float:
        """Triangles at this level as a share of level zero's."""
        return self._share

    _share: float = 1.0


class LODProbe:
    """Renders a mesh offscreen so two levels can be compared pixel for pixel.

    Deliberately plain: one directional light and a specular term, no textures,
    no shadows, no tone mapping. What is being measured is what the *geometry*
    does to the picture, and a material would both hide silhouette changes under
    its own detail and make the number depend on the material.

    Needs a current GL context of at least 3.3 core. The caller owns the
    context; this owns the framebuffer, the program and the buffers, and gives
    them back when it is released.
    """

    VERTEX = """#version 330 core
layout(location = 2) in vec3 aPosition;
layout(location = 1) in vec3 aNormal;
uniform mat4 projection;
uniform mat4 modelview;
uniform mat3 normalMatrix;
out vec3 eyeNormal;
out vec3 eyePosition;
void main() {
    vec4 eye = modelview * vec4(aPosition, 1.0);
    eyePosition = eye.xyz;
    eyeNormal = normalMatrix * aNormal;
    gl_Position = projection * eye;
}
"""

    FRAGMENT = """#version 330 core
in vec3 eyeNormal;
in vec3 eyePosition;
out vec4 fragColour;
void main() {
    vec3 normal = normalize(eyeNormal);
    vec3 toLight = normalize(vec3(0.35, 0.55, 1.0));
    vec3 toEye = normalize(-eyePosition);
    vec3 halfway = normalize(toLight + toEye);
    float lambert = max(dot(normal, toLight), 0.0);
    float gloss = pow(max(dot(normal, halfway), 0.0), 40.0);
    // A little ambient so a face turned away is still on the silhouette, and a
    // sharp specular because a highlight is where a normal error shows first.
    fragColour = vec4(vec3(0.10 + 0.75 * lambert + 0.45 * gloss), 1.0);
}
"""

    def __init__(self, size: int = 512) -> None:
        self.size = int(size)
        self._program = 0
        self._framebuffer = 0
        self._renderbuffers: list[int] = []
        self._build()

    def _build(self) -> None:
        from OpenGL.GL import (
            GL_COLOR_ATTACHMENT0,
            GL_DEPTH_ATTACHMENT,
            GL_DEPTH_COMPONENT24,
            GL_FRAGMENT_SHADER,
            GL_FRAMEBUFFER,
            GL_FRAMEBUFFER_COMPLETE,
            GL_RENDERBUFFER,
            GL_RGBA8,
            GL_VERTEX_SHADER,
            glBindFramebuffer,
            glBindRenderbuffer,
            glCheckFramebufferStatus,
            glFramebufferRenderbuffer,
            glGenFramebuffers,
            glGenRenderbuffers,
            glRenderbufferStorage,
        )
        from OpenGL.GL.shaders import compileProgram, compileShader

        self._program = compileProgram(
            compileShader(self.VERTEX, GL_VERTEX_SHADER),
            compileShader(self.FRAGMENT, GL_FRAGMENT_SHADER),
            validate=False,
        )
        self._framebuffer = int(glGenFramebuffers(1))
        glBindFramebuffer(GL_FRAMEBUFFER, self._framebuffer)
        for attachment, storage in (
            (GL_COLOR_ATTACHMENT0, GL_RGBA8),
            (GL_DEPTH_ATTACHMENT, GL_DEPTH_COMPONENT24),
        ):
            name = int(glGenRenderbuffers(1))
            self._renderbuffers.append(name)
            glBindRenderbuffer(GL_RENDERBUFFER, name)
            glRenderbufferStorage(GL_RENDERBUFFER, storage, self.size, self.size)
            glFramebufferRenderbuffer(GL_FRAMEBUFFER, attachment, GL_RENDERBUFFER, name)
        complete = glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE
        glBindFramebuffer(GL_FRAMEBUFFER, 0)
        if not complete:
            raise RuntimeError("offscreen framebuffer incomplete at %dx%d" % (self.size, self.size))

    def render(
        self,
        positions: Any,
        normals: Any,
        indices: Any,
        distance: float,
        radius: float,
        centre: Any,
        fovy: float = 45.0,
        rotation: float = 0.0,
    ) -> Any:
        """One render, as an ``(n, n, 3)`` array of bytes.

        ``distance`` is from the camera to ``centre``, in the same units as the
        mesh. The near plane is set from it rather than fixed, so a camera a
        millimetre from the surface still has usable depth precision -- which is
        what the close end of a sweep asks for.
        """
        from OpenGL.GL import (
            GL_ARRAY_BUFFER,
            GL_COLOR_BUFFER_BIT,
            GL_DEPTH_BUFFER_BIT,
            GL_DEPTH_TEST,
            GL_ELEMENT_ARRAY_BUFFER,
            GL_FALSE,
            GL_FLOAT,
            GL_FRAMEBUFFER,
            GL_RGB,
            GL_STATIC_DRAW,
            GL_TRIANGLES,
            GL_UNSIGNED_BYTE,
            GL_UNSIGNED_INT,
            glBindBuffer,
            glBindFramebuffer,
            glBindVertexArray,
            glBufferData,
            glClear,
            glClearColor,
            glDeleteBuffers,
            glDeleteVertexArrays,
            glDrawElements,
            glEnable,
            glEnableVertexAttribArray,
            glGenBuffers,
            glGenVertexArrays,
            glGetUniformLocation,
            glReadPixels,
            glUniformMatrix3fv,
            glUniformMatrix4fv,
            glUseProgram,
            glVertexAttribPointer,
            glViewport,
        )

        positions = np.ascontiguousarray(positions, dtype="f4")
        normals = np.ascontiguousarray(normals, dtype="f4")
        indices = np.ascontiguousarray(indices, dtype=np.uint32).reshape(-1)

        vao = int(glGenVertexArrays(1))
        glBindVertexArray(vao)
        buffers = [int(b) for b in glGenBuffers(3)]
        for buffer, data, location in (
            (buffers[0], positions, 2),
            (buffers[1], normals, 1),
        ):
            glBindBuffer(GL_ARRAY_BUFFER, buffer)
            glBufferData(GL_ARRAY_BUFFER, data.nbytes, data, GL_STATIC_DRAW)
            glEnableVertexAttribArray(location)
            glVertexAttribPointer(location, 3, GL_FLOAT, GL_FALSE, 0, None)
        glBindBuffer(GL_ELEMENT_ARRAY_BUFFER, buffers[2])
        glBufferData(GL_ELEMENT_ARRAY_BUFFER, indices.nbytes, indices, GL_STATIC_DRAW)

        try:
            glBindFramebuffer(GL_FRAMEBUFFER, self._framebuffer)
            glViewport(0, 0, self.size, self.size)
            glClearColor(0.0, 0.0, 0.0, 1.0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glEnable(GL_DEPTH_TEST)
            glUseProgram(self._program)

            near = max(distance - radius, distance * 1e-3, 1e-6)
            projection = _perspective(fovy, 1.0, near, distance + 3.0 * radius + 1e-6)
            modelview = _look_at(distance, radius, np.asarray(centre, dtype="d"), rotation)
            glUniformMatrix4fv(
                glGetUniformLocation(self._program, "projection"),
                1,
                GL_FALSE,
                np.ascontiguousarray(projection.T, dtype="f4"),
            )
            glUniformMatrix4fv(
                glGetUniformLocation(self._program, "modelview"),
                1,
                GL_FALSE,
                np.ascontiguousarray(modelview.T, dtype="f4"),
            )
            glUniformMatrix3fv(
                glGetUniformLocation(self._program, "normalMatrix"),
                1,
                GL_FALSE,
                np.ascontiguousarray(modelview[:3, :3].T, dtype="f4"),
            )

            glDrawElements(GL_TRIANGLES, len(indices), GL_UNSIGNED_INT, None)
            raw = glReadPixels(0, 0, self.size, self.size, GL_RGB, GL_UNSIGNED_BYTE)
            # GL reads bottom row first; flip so a saved picture is the right way
            # up. The metric is unaffected either way, but a contact sheet that
            # is upside down is a contact sheet nobody checks the numbers against.
            return np.frombuffer(raw, np.uint8).reshape(self.size, self.size, 3)[::-1]
        finally:
            glBindFramebuffer(GL_FRAMEBUFFER, 0)
            glBindVertexArray(0)
            glDeleteBuffers(3, buffers)
            glDeleteVertexArrays(1, [vao])

    def release(self) -> None:
        """Give the framebuffer, its renderbuffers and the program back."""
        from OpenGL.GL import (
            glDeleteFramebuffers,
            glDeleteProgram,
            glDeleteRenderbuffers,
        )

        if self._renderbuffers:
            glDeleteRenderbuffers(len(self._renderbuffers), self._renderbuffers)
            self._renderbuffers = []
        if self._framebuffer:
            glDeleteFramebuffers(1, [self._framebuffer])
            self._framebuffer = 0
        if self._program:
            glDeleteProgram(self._program)
            self._program = 0

    def __enter__(self) -> LODProbe:
        return self

    def __exit__(self, *_exception: Any) -> None:
        self.release()


def _perspective(fovy: float, aspect: float, near: float, far: float) -> Any:
    """A perspective projection, row-major with the translation in the last row."""
    f = 1.0 / np.tan(np.radians(fovy) / 2.0)
    out = np.zeros((4, 4), dtype="d")
    out[0, 0] = f / aspect
    out[1, 1] = f
    out[2, 2] = (far + near) / (near - far)
    out[2, 3] = -1.0
    out[3, 2] = (2.0 * far * near) / (near - far)
    return out.T


def _look_at(distance: float, radius: float, centre: Any, rotation: float) -> Any:
    """Camera ``distance`` from ``centre``, turned ``rotation`` degrees about Y.

    The camera orbits rather than the model, so the light -- which is fixed in
    eye space -- lights every view the same way. Two renders of two levels from
    the same angle are then lit identically, and the difference between them is
    geometry rather than lighting.
    """
    angle = np.radians(rotation)
    turn = np.asarray(
        [
            [np.cos(angle), 0.0, np.sin(angle), 0.0],
            [0.0, 1.0, 0.0, 0.0],
            [-np.sin(angle), 0.0, np.cos(angle), 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        dtype="d",
    )
    del radius
    move = np.eye(4, dtype="d")
    move[:3, 3] = -np.asarray(centre, dtype="d")
    back = np.eye(4, dtype="d")
    back[2, 3] = -distance
    return back @ turn @ move


def measure_chain(
    chain: Any,
    probe: LODProbe,
    distances: Sequence[float],
    budget: float = 0.02,
    rotation: float = 0.0,
) -> list[LevelReport]:
    """Render every level at every distance and say where each becomes usable.

    ``distances`` are multiples of the chain's radius measured **from the
    surface**, increasing, so 0.001 is a camera a thousandth of the object's
    size off the surface -- millimetres, on anything hand-sized -- and 64 is far
    enough that the whole thing covers a few dozen pixels. Measuring from the
    surface rather than from the centre is what keeps the near end meaningful:
    a distance smaller than the radius would put the camera inside the object,
    where there is nothing to compare.

    ``budget`` is the share of the object's pixels allowed to change: 0.02 is
    two per cent, which is about where a switch stops drawing the eye on a
    moving object.

    Level zero is the reference every other level is compared against, so it
    reports a pop of zero everywhere by construction.
    """
    reference = chain[0]
    reports = []
    references = [
        probe.render(
            reference.attributes["POSITION"],
            reference.attributes["NORMAL"],
            reference.indices,
            distance=(1.0 + multiple) * chain.radius,
            radius=chain.radius,
            centre=chain.centre,
            rotation=rotation,
        )
        for multiple in distances
    ]
    for index, level in enumerate(chain):
        pops, outlines, shadings = [], [], []
        for position, multiple in enumerate(distances):
            if index == 0:
                pops.append(0.0)
                outlines.append(0.0)
                shadings.append(0.0)
                continue
            rendered = probe.render(
                level.attributes["POSITION"],
                level.attributes["NORMAL"],
                level.indices,
                distance=(1.0 + multiple) * chain.radius,
                radius=chain.radius,
                centre=chain.centre,
                rotation=rotation,
            )
            outline, shading = pop_breakdown(references[position], rendered)
            pops.append(outline + shading)
            outlines.append(outline)
            shadings.append(shading)
        reports.append(
            LevelReport(
                level=index,
                triangle_count=level.triangle_count,
                error=level.error,
                pops=pops,
                outlines=outlines,
                shadings=shadings,
                safe_at=safe_distance(distances, pops, budget),
                safe_at_outline=safe_distance(distances, outlines, budget),
                _share=level.triangle_count / max(reference.triangle_count, 1),
            )
        )
    return reports
