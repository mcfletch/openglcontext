"""The grid a view is measured against.

An editor's views draw a grid to place things on: one line every so many
units, a heavier one every tenth, in the plane the view looks at. A plan view
and one that turns are ruled across the ground; an elevation is ruled in its
own upright plane, which is where its measurements are.

How closely it is ruled follows the view's scale. A grid at a fixed spacing is
a sheet of solid lines when the view is zoomed out and a bare field when it is
zoomed in, so the step is chosen from the ones a ruler is marked in -- one, two
and five in every decade -- as the one that lands nearest a comfortable number
of pixels apart.

:class:`Grid` is a node the application puts in its scene, once, and a view is
ruled where its :class:`~OpenGLContext.multiview.views.ViewStyle` says
``grid=True``::

    scene.children.append(Grid())
    front = View(OrthoViewPlatform(OrthoView('front')), name='front',
                 style=ViewStyle(background=(0.32, 0.33, 0.35), grid=True))

What a view is ruled with is :func:`lines_for`, which is arithmetic and holds no
GL, so it can be asked and tested without a window.
"""
from __future__ import annotations

import math
from typing import Any, NamedTuple, Optional

import numpy as np
from vrml import field, node
from vrml.vrml97 import nodetypes

from OpenGLContext.multiview.views import View

__all__ = ['Grid', 'GridLines', 'lines_for', 'spacing_for',
           'DECADE', 'WANTED_PIXELS', 'HEAVY_EVERY']

#: The base the steps are chosen in: one, two and five of every power of ten.
DECADE = 10.0

#: How far apart the lines are aimed to be, in pixels. The step chosen is the
#: one of a ruler's that lands nearest this.
WANTED_PIXELS = 24.0

#: Every so many lines is drawn heavier, so the eye can count along the grid
#: rather than measuring it.
HEAVY_EVERY = 10

#: The steps a ruler is marked in, within one decade.
STEPS = (1.0, 2.0, 5.0)

Point = tuple[float, float, float]


class GridLines(NamedTuple):
    """What a view's grid is drawn from.

    ``segments`` are the lines as world-space pairs, ``heavy`` the indices of
    those drawn heavier, and ``spacing`` how many units apart they are.
    """

    segments: list[tuple[Point, Point]]
    heavy: list[int]
    spacing: float


def spacing_for(shown: float, pixels: int) -> float:
    """How many units apart to rule a view showing ``shown`` units in ``pixels``.

    One of :data:`STEPS` in some decade: the one that puts the lines nearest
    :data:`WANTED_PIXELS` apart, so a grid stays readable at any zoom.
    """
    shown = abs(float(shown))
    pixels = abs(int(pixels))
    if shown <= 0.0 or pixels <= 0:
        return 1.0
    wanted = shown * WANTED_PIXELS / pixels
    power = math.floor(math.log10(wanted)) if wanted > 0 else 0
    best, nearest = STEPS[0] * DECADE ** power, None
    for reach in (power, power + 1):
        for step in STEPS:
            candidate = step * DECADE ** reach
            apart = abs(math.log10(candidate / wanted))
            if nearest is None or apart < nearest:
                best, nearest = candidate, apart
    return best


def _plane(view: View) -> Optional[tuple[np.ndarray, np.ndarray, Point, float]]:
    """The two world directions a view is ruled along, its middle, and its scale.

    An elevation is ruled in its own plane; a plan view and one that turns are
    ruled across the ground, which is the plane things stand on.
    """
    camera = getattr(view.camera, 'view', None)
    if camera is None:
        return None
    across = np.array([1.0, 0.0, 0.0])
    along = np.array([0.0, 0.0, 1.0])
    if hasattr(camera, 'orbit'):                    # a camera that turns
        target = camera.target()
        middle = (float(target[0]), 0.0, float(target[2]))
        shown = 2.0 * camera.distance * math.tan(math.radians(camera.fov) / 2.0)
        return across, along, middle, shown
    centre = tuple(float(value) for value in camera.centre)
    direction = getattr(camera, 'direction', None)
    if direction is None:                           # a plan view of an editor
        return across, along, (centre[0], 0.0, centre[1]), float(camera.span)
    if direction in ('top', 'bottom'):
        middle = (centre[0], 0.0, centre[2])
        return across, along, middle, float(camera.span)
    # An elevation: ruled in the plane it looks at, which is its own axes.
    return (np.asarray(camera.right, 'd'), np.asarray(camera.up, 'd'),
            (centre[0], centre[1], centre[2]), float(camera.span))


def lines_for(view: View, spacing: Optional[float] = None) -> Optional[GridLines]:
    """The lines to rule ``view`` with, or None for a view with no camera.

    The lines stand on the step rather than where the view happens to be, so
    one falls on every round number and the grid reads as a ruler.
    """
    found = _plane(view)
    if found is None:
        return None
    across, along, middle, shown = found
    width, height = view.size
    height = int(height) or 1
    width = int(width) or height
    step = float(spacing) if spacing else spacing_for(shown, height)
    # As much as the view shows, and half again, so a view panned between
    # frames is still ruled to its edges.
    reach = max(shown, shown * width / height) * 0.75
    count = int(math.ceil(reach / step))
    origin = np.asarray(middle, 'd')
    # Where the middle of the view falls on the grid, so the lines are on the
    # step and not on the camera.
    offset_x = round(float(np.dot(origin, across)) / step) * step
    offset_y = round(float(np.dot(origin, along)) / step) * step
    segments: list[tuple[Point, Point]] = []
    heavy: list[int] = []
    for direction, other, offset, other_offset in (
            (across, along, offset_x, offset_y),
            (along, across, offset_y, offset_x)):
        for index in range(-count, count + 1):
            at = offset + index * step
            reach_to = other_offset + reach
            reach_from = other_offset - reach
            start = direction * at + other * reach_from
            end = direction * at + other * reach_to
            if round(at / step) % HEAVY_EVERY == 0:
                heavy.append(len(segments))
            segments.append((
                (float(start[0]), float(start[1]), float(start[2])),
                (float(end[0]), float(end[1]), float(end[2]))))
    return GridLines(segments, heavy, step)


class Grid(nodetypes.Rendering, nodetypes.Children, node.Node):
    """A ruled grid, drawn in each view whose style asks for one.

    The lines are in world coordinates, ruled to each view as it is drawn, so
    where the node sits in the scene moves nothing; put it at the top of the
    scene. ``spacing`` pins how many units apart the lines are, and 0 rules
    each view to its own scale. ``colour`` and ``heavyColour`` are what the
    ordinary and the every-tenth lines are drawn in.

    It takes no picks, casts no shadow, and adds nothing to the scene's bounds.
    """

    PROTO = 'Grid'
    #: How many units apart the lines are; 0 for each view's own scale.
    spacing = field.newField('spacing', 'SFFloat', 1, 0.0)
    #: What the ordinary lines are drawn in.
    colour = field.newField('colour', 'SFColor', 1, (0.35, 0.36, 0.38))
    #: What every tenth line is drawn in.
    heavyColour = field.newField('heavyColour', 'SFColor', 1, (0.5, 0.51, 0.54))

    pickable = False
    castsShadow = False

    def linesFor(self, view: Optional[View]) -> Optional[GridLines]:
        """What to rule ``view`` with, or None where its style asks for no grid."""
        if view is None or not getattr(view.style, 'grid', False):
            return None
        return lines_for(view, float(self.spacing) or None)

    def vertices(self, lines: GridLines) -> np.ndarray:
        """``lines`` as ``(x, y, z, r, g, b)`` rows, two to a segment, for ``GL_LINES``."""
        rows = np.empty((len(lines.segments) * 2, 6), dtype=np.float32)
        if not len(rows):
            return rows
        rows[:, :3] = np.asarray(lines.segments, dtype=np.float32).reshape(-1, 3)
        rows[:, 3:] = np.asarray(self.colour, dtype=np.float32)[:3]
        heavy = np.asarray(lines.heavy, dtype=np.intp)
        if len(heavy):
            colour = np.asarray(self.heavyColour, dtype=np.float32)[:3]
            rows[heavy * 2, 3:] = colour
            rows[heavy * 2 + 1, 3:] = colour
        return rows

    # -- the node protocol the render pass reads ----------------------------
    def sortKey(self, mode: Any, matrix: Any) -> tuple[Any, ...]:
        """Opaque, keyed as a shape with no appearance is."""
        return (False, [], 0.0, [], None)

    def boundingVolume(self, mode: Any) -> Any:
        """A volume with no extent: ruled to each view, so kept by every frustum.

        The base volume has no corners, which is what the frame's frustum test
        keeps and what a union of the scene's bounds passes over.
        """
        from OpenGLContext.scenegraph.boundingvolume import BoundingVolume
        return BoundingVolume()

    def Render(self, mode: Any = None) -> int:
        """Rule the view being drawn, if its style asks for a grid."""
        if (mode is None or getattr(mode, 'shadow_pass', False)
                or not getattr(mode, 'visible', True)):
            return 1
        lines = self.linesFor(getattr(mode, 'view', None))
        if lines is None or not lines.segments:
            return 1
        rows = self.vertices(lines)
        if getattr(mode, 'shader_mode', False):
            self._drawShader(mode, rows)
        else:
            self._drawLegacy(mode, rows)
        return 1

    def _drawShader(self, mode: Any, rows: np.ndarray) -> None:
        """The lines through the pass's per-vertex-colour line program."""
        import ctypes

        from OpenGL import GL as gl
        from OpenGLContext.scenegraph.vertexsemantics import LOC_COLOR, LOC_POSITION
        shader = getattr(mode, 'shader_program', None)
        if shader is None or not shader.use_line():
            return
        try:
            shader.set_matrices(mode.getModelView(), mode.projection,
                                program=shader.line_program)
            buffers = mode.cache.getData(self, key='grid_gpu')
            if buffers is None:
                vao, vbo = int(gl.glGenVertexArrays(1)), int(gl.glGenBuffers(1))
                gl.glBindVertexArray(vao)
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
                stride = rows.strides[0]
                gl.glEnableVertexAttribArray(LOC_POSITION)
                gl.glVertexAttribPointer(LOC_POSITION, 3, gl.GL_FLOAT, gl.GL_FALSE,
                                         stride, None)
                gl.glEnableVertexAttribArray(LOC_COLOR)
                gl.glVertexAttribPointer(LOC_COLOR, 3, gl.GL_FLOAT, gl.GL_FALSE,
                                         stride, ctypes.c_void_p(12))
                gl.glBindVertexArray(0)
                buffers = (vao, vbo)
                mode.cache.holder(self, buffers, key='grid_gpu')
            vao, vbo = buffers
            gl.glBindBuffer(gl.GL_ARRAY_BUFFER, vbo)
            gl.glBufferData(gl.GL_ARRAY_BUFFER, rows.nbytes, rows, gl.GL_STREAM_DRAW)
            gl.glBindVertexArray(vao)
            try:
                gl.glDrawArrays(gl.GL_LINES, 0, len(rows))
            finally:
                gl.glBindVertexArray(0)
                gl.glBindBuffer(gl.GL_ARRAY_BUFFER, 0)
        finally:
            shader.use(lit=True)

    def _drawLegacy(self, mode: Any, rows: np.ndarray) -> None:
        """The lines with the fixed-function pipeline, in the camera's frame."""
        from OpenGL import GL as gl
        gl.glPushAttrib(gl.GL_ENABLE_BIT | gl.GL_CURRENT_BIT)
        gl.glMatrixMode(gl.GL_MODELVIEW)
        gl.glPushMatrix()
        try:
            gl.glLoadMatrixf(np.asarray(mode.getModelView(), dtype=np.float32))
            gl.glDisable(gl.GL_LIGHTING)
            gl.glDisable(gl.GL_TEXTURE_2D)
            gl.glBegin(gl.GL_LINES)
            try:
                for row in rows:
                    gl.glColor3f(float(row[3]), float(row[4]), float(row[5]))
                    gl.glVertex3f(float(row[0]), float(row[1]), float(row[2]))
            finally:
                gl.glEnd()
        finally:
            gl.glPopMatrix()
            gl.glPopAttrib()
