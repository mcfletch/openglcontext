"""Colour-based object selection / picking for shader-based FlatPass.

``FlatPass`` mixes :class:`SelectionMixin` in, so ``self`` is the pass and all the
pass hooks the methods call resolve on the combined class.

This module holds the picking *policy*: pick-event optimisation, the fast MRT
buffer lookup, and the legacy per-pick render fallback. The two selection
framebuffers live in :mod:`selectionbuffers` and the async PBO/fence readback in
:mod:`asyncpick`; both are re-exported / inherited here so importers of
``SelectionFBO`` / ``SelectionBufferFBO`` / ``SelectionMixin`` are unaffected.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple

import numpy as np

from OpenGL.GL import (
    GL_COLOR_BUFFER_BIT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_COMPONENT, GL_FLOAT,
    GL_FRAMEBUFFER, GL_RGBA, GL_SCISSOR_TEST, GL_UNSIGNED_BYTE, glBindFramebuffer,
    glClear, glClearColor, glDisable, glEnable, glReadPixels, glScissor, glViewport,
)
# array/dot/concatenate/ones are numpy names re-exported through vrml.arrays'
# star import, which mypy cannot trace across.
from OpenGLContext.arrays import array, dot, concatenate, ones  # type: ignore[attr-defined]
import logging

from OpenGLContext.passes.selectionbuffers import SelectionFBO, SelectionBufferFBO
from OpenGLContext.passes.asyncpick import _AsyncPickMixin

if TYPE_CHECKING:
    from OpenGLContext.passes.shaderpass import VRML97ShaderProgram

log = logging.getLogger(__name__)

__all__ = ['SelectionFBO', 'SelectionBufferFBO', 'SelectionMixin']


class SelectionMixin(_AsyncPickMixin):
    """Adds colour-based picking (per-pick FBO + MRT id buffer) to a FlatPass."""

    if TYPE_CHECKING:
        visible: bool
        transparent: bool
        lighting: bool
        textured: bool
        renderPath: Any
        modelView: Any
        shader_program: Optional["VRML97ShaderProgram"]

        def getViewport(self) -> Tuple[int, int, int, int]: ...

    # Selection FBO for optimized picking (lazily initialized per instance)
    _selection_fbo: Optional['SelectionFBO'] = None
    # MRT selection buffer for zero-cost picking (lazily initialized)
    _selection_buffer: Optional['SelectionBufferFBO'] = None
    # Enable MRT-based selection (vs legacy per-pick rendering)
    use_mrt_selection: bool = True

    def _getSelectionFBO(self) -> SelectionFBO:
        """Get or create the selection FBO for this pass instance."""
        if self._selection_fbo is None:
            self._selection_fbo = SelectionFBO(max_width=512, max_height=512)
        return self._selection_fbo

    def _getSelectionBuffer(self) -> SelectionBufferFBO:
        """Get or create the MRT selection buffer for this pass instance."""
        if self._selection_buffer is None:
            self._selection_buffer = SelectionBufferFBO()
        return self._selection_buffer

    # Cache for hasMouseMoveHandlers check (cleared each frame)
    _has_mousemove_handlers: Optional[bool] = None

    def _optimizePickEvents(self, context: Any, events: Dict) -> Dict:
        """Optimize pick events by filtering and de-duplicating.

        Optimizations:
        1. Skip mouse-move events if no mousemove/mousein/mouseout handlers registered
        2. De-duplicate events to only keep one per unique pixel coordinate

        Args:
            context: The rendering context
            events: Dictionary of pick events

        Returns:
            Optimized dictionary of pick events (may be empty)
        """
        if not events:
            return events

        original_count = len(events)

        # Check if we have mouse-move handlers (cache per frame for performance)
        if self._has_mousemove_handlers is None:
            self._has_mousemove_handlers = context.hasMouseMoveHandlers()

        has_move_handlers = self._has_mousemove_handlers

        # Filter and de-duplicate events
        # Key: (type, pixel_x, pixel_y) -> event (keeps latest)
        optimized = {}
        filtered_move_count = 0

        for _key, event in events.items():
            event_type = getattr(event, 'type', 'unknown')

            # Skip mouse-move events if no handlers are registered
            if event_type == 'mousemove' and not has_move_handlers:
                filtered_move_count += 1
                continue

            # De-duplicate by pixel, but only across events that are genuinely
            # the same news twice.  Where the pointer is now is all a move has
            # to say and moves arrive in floods, so one per pixel is plenty.
            # Button events at one pixel are not redundant: a press and its
            # release share a pixel by definition, as does every notch of a
            # wheel, and dropping either half of a pair loses the whole input.
            pick_point = event.getPickPoint()
            pixel_x, pixel_y = int(pick_point[0]), int(pick_point[1])
            distinguisher = (None if event_type == 'mousemove'
                             else event.getPickKey())
            dedup_key = (event_type, pixel_x, pixel_y, distinguisher)

            # Always keep the latest event for each unique position
            optimized[dedup_key] = event

        # Log optimization results if significant
        final_count = len(optimized)
        if original_count > 1 and (filtered_move_count > 0 or final_count < original_count):
            log.debug(
                "Pick event optimization: %d -> %d events "
                "(filtered %d moves, deduped %d)",
                original_count, final_count,
                filtered_move_count,
                original_count - filtered_move_count - final_count
            )

        return optimized

    def processPickEventsFromBuffer(self, mode: Any, events: Dict) -> None:
        """Process pick events using the cached MRT selection buffer.

        This is the fast path - no GPU rendering, just CPU array lookups.
        Also retrieves depth values for 3D coordinate unprojection.

        Args:
            mode: Render mode
            events: Pick events dict
        """
        if not events:
            return

        selection_buffer = self._getSelectionBuffer()
        if not selection_buffer._initialized:
            # Buffer not ready, fall back to legacy method
            return

        # The camera's, not self.matrix: the traversal rewrites that for
        # every node it visits, so by dispatch time it holds whatever was
        # drawn last and every picked point would come back in that node's
        # local space.
        matrix = self.modelView
        id_map = getattr(selection_buffer, 'id_map', {}) or {}

        for event in events.values():
            x, y = event.getPickPoint()
            x, y = int(x), int(y)

            # Read just this pixel's id + depth from the FBO (no full readback).
            obj_id, depth = selection_buffer.read_pixel(x, y)
            path = id_map.get(obj_id, [])

            self._dispatchPickEvent(
                mode, event, [path] if path else [[]], x, y, depth,
                matrix, self.projection, self.viewport)

    def _createPickProjection(self, pick_region: Tuple[int, int, int, int],
                              viewport: Tuple[int, int, int, int]) -> np.ndarray:
        """Create a pick projection matrix that zooms into the pick region.

        Args:
            pick_region: (x, y, width, height) of pick region in viewport coords
            viewport: (x, y, width, height) of the full viewport

        Returns:
            Modified projection matrix focused on pick region
        """
        # identity is numpy.identity re-exported through vrml.arrays' star import.
        from OpenGLContext.arrays import identity  # type: ignore[attr-defined]

        px, py, pw, ph = pick_region
        vx, vy, vw, vh = viewport

        # Calculate the scale factors to zoom into the pick region
        scale_x = vw / pw if pw > 0 else 1.0
        scale_y = vh / ph if ph > 0 else 1.0

        # Calculate the translation to center on the pick region
        # The center of the pick region in viewport coords
        pick_center_x = px + pw / 2.0
        pick_center_y = py + ph / 2.0

        # The center of the viewport
        view_center_x = vx + vw / 2.0
        view_center_y = vy + vh / 2.0

        # Translation in NDC space
        trans_x = (view_center_x - pick_center_x) / (vw / 2.0) * scale_x
        trans_y = (view_center_y - pick_center_y) / (vh / 2.0) * scale_y

        # Create pick matrix
        pick_matrix = identity(4, 'f')
        pick_matrix[0, 0] = scale_x
        pick_matrix[1, 1] = scale_y
        pick_matrix[3, 0] = trans_x
        pick_matrix[3, 1] = trans_y

        # Combine with original projection
        return dot(self.projection, pick_matrix)

    def shaderSelectRenderOptimized(self, mode: Any, toRender: List, events: Dict) -> None:
        """Optimized selection render processing each pick point individually.

        For each pick point:
        1. Pre-compute screen-space bounding boxes for all objects (done once)
        2. For each pick point, find objects whose screen bbox contains the point
        3. Render only those few objects (typically 1-10) with unique IDs
        4. Read back the single pixel

        This dramatically reduces rendering load compared to batch processing.

        Args:
            mode: Render mode
            toRender: Render set
            events: Pick events
        """
        if not events:
            return

        self.visible = False
        self.transparent = False
        self.lighting = False
        self.textured = False

        # The camera's, not self.matrix: the traversal rewrites that for
        # every node it visits, so by dispatch time it holds whatever was
        # drawn last and every picked point would come back in that node's
        # local space.
        matrix = self.modelView
        vp = self.getViewport()
        vp_w, vp_h = float(vp[2]), float(vp[3])
        debugSelection = mode.context.contextDefinition.debugSelection

        # Collect pick points grouped by location
        pickPoints: Dict[Any, List] = {}
        for event in events.values():
            x, y = key = tuple(event.getPickPoint())
            pickPoints.setdefault(key, []).append(event)

        if not pickPoints:  # pragma: no cover - unreachable: non-empty events
            return          # always yield at least one pick point above

        # Pre-compute screen-space bounding boxes for all objects (done once)
        # This is the key optimization - project all bounding volumes to screen space
        screen_bboxes = self._computeScreenSpaceBBoxes(toRender, vp_w, vp_h)

        # Set up shader
        shader = self.shader_program
        assert shader is not None  # selection pass only runs with a program bound
        shader.use(lit=False)

        # Use a tiny FBO (3x3) for each pick point
        selection_fbo = self._getSelectionFBO()
        pick_size = 3
        half_pick = pick_size // 2

        pixel = array([0, 0, 0, 0], 'B')
        depth_pixel = array([[0]], 'f')

        try:
            # Process each unique pick point
            for point, eventSet in pickPoints.items():
                px, py = point

                # Skip if outside viewport
                if px < 0 or py < 0 or px >= vp_w or py >= vp_h:
                    for event in eventSet:
                        event.setObjectPaths([[]])
                    continue

                # Find objects whose screen bounding box contains this pick point
                # This is a simple 2D point-in-rect test
                hit_indices = []
                for idx, bbox in enumerate(screen_bboxes):
                    if bbox is None:
                        # No bounding volume - must include
                        hit_indices.append(idx)
                    else:
                        min_x, min_y, max_x, max_y = bbox
                        if min_x <= px <= max_x and min_y <= py <= max_y:
                            hit_indices.append(idx)

                if not hit_indices:
                    # No objects under this point
                    for event in eventSet:
                        event.setObjectPaths([[]])
                    continue

                # Set up tiny FBO for this pick point
                region_x = int(max(0, px - half_pick))
                region_y = int(max(0, py - half_pick))
                region_w = min(pick_size, int(vp_w) - region_x)
                region_h = min(pick_size, int(vp_h) - region_y)

                use_fbo = not debugSelection and selection_fbo.bind(
                    region_x, region_y, region_w, region_h
                )

                if use_fbo:
                    pick_region = (region_x, region_y, region_w, region_h)
                    pick_projection = self._createPickProjection(pick_region, vp)
                    glClearColor(0, 0, 0, 0)
                    glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)
                else:
                    pick_projection = self.projection
                    if not debugSelection:
                        glScissor(region_x, region_y, region_w, region_h)
                        glEnable(GL_SCISSOR_TEST)
                    glClearColor(0, 0, 0, 0)
                    glClear(GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)

                # Render only the objects that may be under this pick point
                id_map = {}
                for obj_id, idx in enumerate(hit_indices):
                    key, mvmatrix, tmatrix, bvolume, path = toRender[idx]
                    color_id = (obj_id + 1) << 12

                    r = (color_id >> 0) & 0xFF
                    g = (color_id >> 8) & 0xFF
                    b = (color_id >> 16) & 0xFF

                    shader.use(lit=False)
                    shader.set_solid_color((r / 255.0, g / 255.0, b / 255.0, 1.0))
                    shader.set_matrices(mvmatrix, pick_projection, program=shader.unlit_program)

                    self.matrix = mvmatrix
                    self.renderPath = path
                    path[-1].Render(mode=self)
                    id_map[color_id] = path

                # Read back the center pixel
                if use_fbo:
                    read_x = int(px) - region_x
                    read_y = int(py) - region_y
                    read_x = max(0, min(region_w - 1, read_x))
                    read_y = max(0, min(region_h - 1, read_y))
                else:
                    read_x, read_y = int(px), int(py)

                glReadPixels(read_x, read_y, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel)
                # id_map is keyed by the 24-bit RGB colour id; the solid-colour
                # fill writes alpha 1.0 (0xFF) so the fragment survives, so mask
                # the alpha byte out of the packed readback before the lookup.
                lpixel = int(pixel.view('<I')[0]) & 0xFFFFFF
                paths = id_map.get(lpixel, [])

                glReadPixels(read_x, read_y, 1, 1, GL_DEPTH_COMPONENT, GL_FLOAT, depth_pixel)

                for event in eventSet:
                    self._dispatchPickEvent(
                        mode, event, [paths], int(px), int(py), depth_pixel[0][0],
                        matrix, self.projection, self.viewport)

                # Clean up for this pick point
                if use_fbo:
                    selection_fbo.unbind()
                else:
                    glDisable(GL_SCISSOR_TEST)

        finally:
            shader.unuse()
            # Restore viewport
            glViewport(*[int(v) for v in vp])
            # Never leak the pick FBO binding or the scissor enable into the next
            # frame: an exception mid-pick-loop skips a point's own
            # cleanup, so restore both defensively here (idempotent).
            try:
                glBindFramebuffer(GL_FRAMEBUFFER, 0)
            except Exception as err:
                log.debug("pick-loop FBO restore failed: %s", err)
            glDisable(GL_SCISSOR_TEST)

    def _computeScreenSpaceBBoxes(self, toRender: List, vp_w: float, vp_h: float) -> List:
        """Pre-compute screen-space bounding boxes for all objects.

        Projects each object's bounding volume corners to screen space and
        computes the 2D bounding box.

        Args:
            toRender: Render set
            vp_w: Viewport width
            vp_h: Viewport height

        Returns:
            List of (min_x, min_y, max_x, max_y) tuples or None for objects without bounds
        """
        result: List[Optional[Tuple[float, float, float, float]]] = []

        for record in toRender:
            key, mvmatrix, tmatrix, bvolume, path = record

            if bvolume is None:
                result.append(None)
                continue

            try:
                points = bvolume.getPoints()
                if len(points) == 0:
                    result.append(None)
                    continue

                # Transform to clip space: point * modelview * projection
                mvp = dot(mvmatrix, self.projection)

                if points.shape[1] == 3:
                    points_4d = concatenate([points, ones((len(points), 1), dtype='f')], axis=1)
                else:
                    points_4d = points

                clip_points = dot(points_4d, mvp)

                # Perspective divide to NDC
                # Filter out points behind camera (w <= 0)
                valid_mask = clip_points[:, 3] > 0.001
                if not valid_mask.any():
                    # All points behind camera - skip
                    result.append(None)
                    continue

                valid_points = clip_points[valid_mask]
                ndc = valid_points[:, :3] / valid_points[:, 3:4]

                # Convert NDC to screen coordinates
                screen_x = (ndc[:, 0] + 1.0) * 0.5 * vp_w
                screen_y = (ndc[:, 1] + 1.0) * 0.5 * vp_h

                min_x = float(screen_x.min())
                max_x = float(screen_x.max())
                min_y = float(screen_y.min())
                max_y = float(screen_y.max())

                result.append((min_x, min_y, max_x, max_y))

            except Exception:
                result.append(None)

        return result
