"""Textures the render pass draws: GeneratedCubeMapTexture and RenderedTexture

A ``GeneratedCubeMapTexture`` is the scene drawn into the six faces of a cube
from the local origin of the shape wearing it, and a ``RenderedTexture`` the
scene (or its own ``scene``) drawn into a picture from its ``viewpoint`` (or
the camera's). Each frame draws, before any view, the ones the frame before
asked for (:class:`GeneratedSchedule`, no GL): a texture asks by being drawn,
which is when its node's ``cached(mode)`` calls :meth:`GeneratedTexturesMixin.generatedTexture`.
A texture's first drawing therefore shows a frame after the shape wearing it
first does; the pass asks for that frame.

``update`` says when one is drawn again: ``NONE`` never, once it has been
drawn once; ``NEXT_FRAME_ONLY`` once more, after which the node's ``update``
is set to ``NONE``; ``ALWAYS`` with every frame the scene is drawn. A drawing
leaves out the shapes wearing the texture, which would otherwise read the
texture being drawn. Both are drawn in the shader passes; the compatibility
profile draws neither.
"""
from __future__ import annotations

import contextlib
import logging
import math
import weakref
from collections.abc import Iterator, Sequence
from typing import Any, NamedTuple, Optional

import numpy as np
from OpenGL.GL import (
    GL_CLAMP_TO_EDGE, GL_COLOR_ATTACHMENT0, GL_COLOR_BUFFER_BIT, GL_COLOR_CLEAR_VALUE,
    GL_DEPTH_ATTACHMENT, GL_DEPTH_BUFFER_BIT, GL_DEPTH_COMPONENT, GL_DEPTH_COMPONENT24,
    GL_FLOAT, GL_FRAMEBUFFER, GL_FRAMEBUFFER_BINDING, GL_FRAMEBUFFER_COMPLETE, GL_LINEAR,
    GL_LINEAR_MIPMAP_LINEAR, GL_NONE, GL_ONE, GL_RED, GL_RGBA, GL_RGBA8, GL_TEXTURE_2D,
    GL_TEXTURE_COMPARE_MODE, GL_TEXTURE_CUBE_MAP, GL_TEXTURE_MAG_FILTER,
    GL_TEXTURE_MIN_FILTER, GL_TEXTURE_SWIZZLE_A, GL_TEXTURE_SWIZZLE_B, GL_TEXTURE_SWIZZLE_G,
    GL_TEXTURE_SWIZZLE_R, GL_TEXTURE_WRAP_S, GL_TEXTURE_WRAP_T, GL_UNSIGNED_BYTE, GL_VIEWPORT,
    glBindFramebuffer, glBindTexture, glCheckFramebufferStatus, glClear, glClearColor,
    glDeleteFramebuffers, glDeleteTextures, glFramebufferTexture2D, glGenFramebuffers,
    glGenTextures, glGenerateMipmap, glGetFloatv, glGetIntegerv, glTexImage2D,
    glTexParameteri, glViewport,
)

log = logging.getLogger(__name__)

__all__ = ['GLTexture', 'GeneratedSchedule', 'GeneratedTexturesMixin', 'PictureTarget',
           'UPDATES']

#: X3D's update modes.
UPDATES = ('NONE', 'NEXT_FRAME_ONLY', 'ALWAYS')


class GLTexture(NamedTuple):
    """A texture the pass draws, as a texture node's ``cached`` answers one"""

    texture: int
    target: int
    #: Channels, as a texture holder gives them.
    components: int = 4


def wears(shape: Any, texture: Any) -> bool:
    """Whether ``shape``'s appearance wears ``texture``, itself or as a layer"""
    worn = getattr(getattr(shape, 'appearance', None), 'texture', None)
    if worn is texture:
        return True
    from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept beside its one use
    return isinstance(worn, x3d.MultiTexture) and any(layer is texture for layer in worn.texture)


class GeneratedSchedule:
    """Which generated textures to draw this frame, and from where -- no GL

    :meth:`request` is told of each drawing of a shape wearing one;
    :meth:`take` answers, once a frame, the textures due and the paths of the
    shapes that asked, and starts the record for the next frame.
    """

    def __init__(self) -> None:
        self._asked: weakref.WeakKeyDictionary[Any, list[Any]] = weakref.WeakKeyDictionary()
        self._drawn: weakref.WeakKeyDictionary[Any, int] = weakref.WeakKeyDictionary()

    def request(self, node: Any, path: Any = None) -> bool:
        """``node`` was drawn on the shape at ``path``; whether it is new and due

        A texture never drawn that is due asks for a frame to be drawn in.
        """
        paths = self._asked.get(node)
        first = paths is None
        if first:
            paths = self._asked[node] = []
        if path is not None and not any(path is held for held in paths):
            paths.append(path)
        return first and not self.drawn(node) and self.due(node)

    def drawn(self, node: Any) -> int:
        """How many times ``node`` has been drawn"""
        return self._drawn.get(node, 0)

    def due(self, node: Any) -> bool:
        """Whether ``node``'s ``update`` asks for a drawing now"""
        update = str(getattr(node, 'update', 'NONE') or 'NONE')
        if update in ('ALWAYS', 'NEXT_FRAME_ONLY'):
            return True
        return not self.drawn(node)

    def take(self) -> list[tuple[Any, list[Any]]]:
        """The textures asked for and due, each with the paths that asked

        Clears the record, so the next frame's drawings make the next one.
        """
        found = [(node, paths) for node, paths in list(self._asked.items())
                 if self.due(node)]
        self._asked = weakref.WeakKeyDictionary()
        return found

    def finished(self, node: Any) -> None:
        """``node`` was drawn: a ``NEXT_FRAME_ONLY`` becomes ``NONE``"""
        self._drawn[node] = self.drawn(node) + 1
        if str(getattr(node, 'update', '')) == 'NEXT_FRAME_ONLY':
            node.update = 'NONE'


class PictureTarget:
    """A colour texture and a depth texture a RenderedTexture is drawn into"""

    def __init__(self, width: int, height: int) -> None:
        self.width, self.height = max(1, int(width)), max(1, int(height))
        self.colour: Optional[int] = None
        self.depth: Optional[int] = None
        self._fbo: Optional[int] = None
        self._previous = 0
        self._viewport: tuple[int, int, int, int] = (0, 0, 0, 0)
        self._clear: tuple[float, float, float, float] = (0.0, 0.0, 0.0, 0.0)

    def _ensure(self) -> None:
        if self.colour is not None:
            return
        colour = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, colour)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, self.width, self.height, 0, GL_RGBA,
                     GL_UNSIGNED_BYTE, None)
        for name, value in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR_MIPMAP_LINEAR),
                            (GL_TEXTURE_MAG_FILTER, GL_LINEAR)):
            glTexParameteri(GL_TEXTURE_2D, name, value)
        depth = int(glGenTextures(1))
        glBindTexture(GL_TEXTURE_2D, depth)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_DEPTH_COMPONENT24, self.width, self.height, 0,
                     GL_DEPTH_COMPONENT, GL_FLOAT, None)
        # Read as a luminance picture of the depth: no comparison, the depth
        # in every channel and an opaque alpha.
        for name, value in ((GL_TEXTURE_MIN_FILTER, GL_LINEAR), (GL_TEXTURE_MAG_FILTER, GL_LINEAR),
                            (GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE),
                            (GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE),
                            (GL_TEXTURE_COMPARE_MODE, GL_NONE),
                            (GL_TEXTURE_SWIZZLE_R, GL_RED), (GL_TEXTURE_SWIZZLE_G, GL_RED),
                            (GL_TEXTURE_SWIZZLE_B, GL_RED), (GL_TEXTURE_SWIZZLE_A, GL_ONE)):
            glTexParameteri(GL_TEXTURE_2D, name, value)
        glBindTexture(GL_TEXTURE_2D, 0)
        self.colour, self.depth = colour, depth
        self._fbo = int(glGenFramebuffers(1))

    def begin(self) -> None:
        """Draw into the picture, cleared, from here on; :meth:`end` puts back the
        caller's target, viewport and clear colour"""
        self._previous = int(glGetIntegerv(GL_FRAMEBUFFER_BINDING))
        x, y, width, height = (int(v) for v in glGetIntegerv(GL_VIEWPORT))
        self._viewport = (x, y, width, height)
        red, green, blue, alpha = (float(v) for v in glGetFloatv(GL_COLOR_CLEAR_VALUE))
        self._clear = (red, green, blue, alpha)
        self._ensure()
        assert self._fbo is not None
        glBindFramebuffer(GL_FRAMEBUFFER, self._fbo)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D,
                               self.colour, 0)
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_DEPTH_ATTACHMENT, GL_TEXTURE_2D,
                               self.depth, 0)
        status = int(glCheckFramebufferStatus(GL_FRAMEBUFFER))
        if status != GL_FRAMEBUFFER_COMPLETE:
            raise RuntimeError('rendered texture target incomplete: 0x%x' % (status,))
        glViewport(0, 0, self.width, self.height)
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)

    def end(self) -> None:
        """Give the caller's target back, and make the picture's mips"""
        glBindFramebuffer(GL_FRAMEBUFFER, self._previous)
        glViewport(*self._viewport)
        glClearColor(*self._clear)
        if self.colour is not None:
            glBindTexture(GL_TEXTURE_2D, self.colour)
            glGenerateMipmap(GL_TEXTURE_2D)
            glBindTexture(GL_TEXTURE_2D, 0)

    def release(self) -> None:
        """Let go of the GL objects"""
        try:
            if self._fbo is not None:
                glDeleteFramebuffers(1, np.array([self._fbo], dtype=np.uint32))
            for name in (self.colour, self.depth):
                if name is not None:
                    glDeleteTextures(1, np.array([name], dtype=np.uint32))
        except Exception as err:     # pragma: no cover - teardown after the context
            log.debug('rendered texture target teardown: %s', err)
        self.colour = self.depth = self._fbo = None


class _SceneWalk:
    """The paths of a scene that is not the pass's, walked as the pass walks its own"""

    def __init__(self, scene: Any, owner: Any) -> None:
        from OpenGLContext.passes._flat import SGObserver  # noqa: PLC0415 _flat imports this module
        self.paths: dict[type, list[Any]] = {}
        self.nodePaths: dict[Any, list[Any]] = {}
        self.contexts: tuple[()] = ()
        self.INTERESTING_TYPES = owner.INTERESTING_TYPES
        SGObserver.integrate(self, scene)  # type: ignore[arg-type]  # walked with the observer's own walk, with no subscriptions

    def npFor(self, node: Any) -> list[Any]:
        return self.nodePaths.setdefault(node, [])

    def _pathSetChanged(self) -> None:
        return None

    @property
    def _hidden(self) -> dict[Any, list[Any]]:
        return self.__dict__.setdefault('_hiddenNodes', {})


class GeneratedTexturesMixin:
    """The pass's side: asking for generated textures, and drawing them"""

    #: Each generated texture's GL target in this pass's context.
    _generatedTargets: Optional[weakref.WeakKeyDictionary[Any, Any]] = None
    _generatedSchedule: Optional[GeneratedSchedule] = None
    #: Whether a generated texture is being drawn: its own draws ask for nothing.
    _generating: Any = None

    def generatedSchedule(self) -> GeneratedSchedule:
        """The schedule of this pass's generated textures"""
        if self._generatedSchedule is None:
            self._generatedSchedule = GeneratedSchedule()
        return self._generatedSchedule

    def _targets(self) -> weakref.WeakKeyDictionary[Any, Any]:
        if self._generatedTargets is None:
            self._generatedTargets = weakref.WeakKeyDictionary()
        return self._generatedTargets

    def generatedTexture(self, node: Any) -> Optional[GLTexture]:
        """The texture ``node`` was last drawn into, or None before its first drawing

        Asking records that the shape being drawn wears it.
        """
        if not getattr(self, 'shader_mode', False):
            return None
        path = getattr(self, 'renderPath', None)
        if path is not None and not wears(path[-1], node):
            path = None
        if self._generating is None and self.generatedSchedule().request(node, path):
            trigger = getattr(getattr(self, 'context', None), 'triggerRedraw', None)
            if trigger is not None:
                trigger(0)
        target = self._targets().get(node)
        if target is None or not self.generatedSchedule().drawn(node):
            return None
        if isinstance(target, PictureTarget):
            name = target.depth if bool(getattr(node, 'depthMap', False)) else target.colour
            return None if name is None else GLTexture(name, GL_TEXTURE_2D)
        return None if target.cube is None else GLTexture(target.cube, GL_TEXTURE_CUBE_MAP)

    def disposeResources(self) -> None:
        """Release the generated textures' targets"""
        for target in list(self._targets().values()):
            try:
                target.release()
            except Exception:     # pragma: no cover - teardown after the context
                log.debug('generated texture teardown failed', exc_info=True)
        self._generatedTargets = None
        self._generatedSchedule = None
        super().disposeResources()  # type: ignore[misc]  # the pass's chain of mixins ends in one

    def renderGeneratedTextures(self, frames: Sequence[Any], lighting: Any) -> None:
        """Draw the generated textures the last frame asked for, before any view is drawn"""
        schedule = self.generatedSchedule()
        due = schedule.take()
        for node, paths in due:
            try:
                if self._drawGenerated(node, paths, frames, lighting):
                    schedule.finished(node)
            except Exception:
                log.exception('the generated texture %s could not be drawn', node)
                schedule.finished(node)

    def _drawGenerated(self, node: Any, paths: list[Any], frames: Sequence[Any],
                       lighting: Any) -> bool:
        from vrml.x3d import nodes as x3d  # noqa: PLC0415 kept beside its one use
        template = self.activeFrame if self.activeFrame is not None else (  # type: ignore[attr-defined]  # the pass's
            frames[0] if frames else None)
        if template is None or getattr(self, 'shader_program', None) is None:
            return False
        if isinstance(node, x3d.GeneratedCubeMapTexture):
            return self._drawCube(node, paths, template, lighting)
        return self._drawPicture(node, paths, template, lighting)

    # -- the drawings ----------------------------------------------------------
    def _drawCube(self, node: Any, paths: list[Any], template: Any, lighting: Any) -> bool:
        from OpenGLContext.passes import shadowmath  # noqa: PLC0415 kept with the drawing
        from OpenGLContext.passes.zoneprobes import CaptureTarget  # noqa: PLC0415 GL target
        if not paths:
            return False
        size = max(1, int(node.size))
        targets = self._targets()
        target = targets.get(node)
        if target is None or target.size != size:
            if target is not None:
                target.release()
            target = targets[node] = CaptureTarget(size)
        centre = np.asarray(paths[0].transformMatrix(), 'd')[3, :3]
        near, far = self._depthRange(template)
        projection = shadowmath.cube_projection(near, far)
        target.begin()
        try:
            for face in range(6):
                view = shadowmath.cube_face_view(centre, face)
                target.face(face)
                self._drawView(view, projection, (0, 0, size, size), template, lighting,
                               paths, None)
        finally:
            target.end(whole=True)
        return True

    def _drawPicture(self, node: Any, paths: list[Any], template: Any, lighting: Any) -> bool:
        width, height = max(1, int(node.width)), max(1, int(node.height))
        targets = self._targets()
        target = targets.get(node)
        if target is None or (target.width, target.height) != (width, height):
            if target is not None:
                target.release()
            target = targets[node] = PictureTarget(width, height)
        walk = _SceneWalk(node.scene, self) if getattr(node, 'scene', None) else None
        view, projection = self._pictureCamera(node, template, width / height, walk)
        target.begin()
        try:
            self._drawView(view, projection, (0, 0, width, height), template, lighting,
                           paths, node, walk)
        finally:
            target.end()
        return True

    def _pictureCamera(self, node: Any, template: Any, aspect: float,
                       walk: Optional[_SceneWalk]) -> tuple[Any, Any]:
        """(view, projection) a RenderedTexture is drawn with"""
        from OpenGLContext.multiview.viewpoints import camera_at  # noqa: PLC0415 kept with its use
        from OpenGLContext.passes import shadowmath  # noqa: PLC0415 kept with its use
        near, far = self._depthRange(template)
        viewpoint = getattr(node, 'viewpoint', None)
        if viewpoint:
            held = (walk.nodePaths if walk is not None else getattr(self, 'nodePaths', {})).get(
                viewpoint) or []
            matrix = held[0].transformMatrix() if held else None
            camera = camera_at(viewpoint, matrix)
            view = shadowmath.look_at_matrix(camera.position, camera.forward, camera.up)
            return view, shadowmath.perspective_matrix(camera.fov, aspect, near, far)
        try:
            fovy = math.radians(float(template.camera.frustum[0]))
        except (AttributeError, TypeError, ValueError, IndexError):
            fovy = math.pi / 4
        return template.modelView, shadowmath.perspective_matrix(fovy, aspect, near, far)

    @staticmethod
    def _depthRange(template: Any) -> tuple[float, float]:
        try:
            _fovy, _aspect, near, far = template.camera.frustum
            return max(float(near), 0.05), max(float(far), float(near) * 2.0)
        except (AttributeError, TypeError, ValueError):
            return 0.1, 1000.0

    @contextlib.contextmanager
    def _scenePaths(self, rendered: Any, walk: Optional[_SceneWalk]) -> Iterator[None]:
        """The pass's paths are the RenderedTexture's scene's, with its background
        and fog, for the block"""
        from vrml.vrml97 import nodetypes  # noqa: PLC0415 kept with its use
        from OpenGLContext.scenegraph import nodepath  # noqa: PLC0415 kept with its use
        owner: Any = self
        before = owner.paths
        paths = dict(walk.paths if walk is not None else before)
        for name, kind in (('background', nodetypes.Background), ('fog', nodetypes.Fog)):
            chosen = getattr(rendered, name, None) if rendered is not None else None
            if chosen:
                paths[kind] = [nodepath.NodePath([chosen])]
        changed = walk is not None or paths.keys() != before.keys() or any(
            paths[key] is not before[key] for key in paths)
        if changed:
            owner.paths = paths
        try:
            yield
        finally:
            if changed:
                owner.paths = before

    def _drawView(self, view: Any, projection: Any, rect: tuple[int, int, int, int],
                  template: Any, lighting: Any, paths: list[Any], rendered: Any,
                  walk: Optional[_SceneWalk] = None) -> None:
        """Draw the scene through ``view`` into the bound target, without ``paths``' shapes"""
        from OpenGLContext import frustum as frustummodule  # noqa: PLC0415 kept with the drawing
        from OpenGLContext.multiview.strategy import ViewFrame  # noqa: PLC0415 kept with the drawing
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh  # noqa: PLC0415 GL
        owner: Any = self
        shader = owner.shader_program
        modelproj = np.dot(view, projection)
        frame = ViewFrame(
            template.view, template.camera, rect, view, projection, modelproj,
            frustummodule.Frustum.fromViewingMatrix(modelproj, normalize=1), fitted=False)
        active = owner.activeFrame
        lookups = getattr(owner, '_reflection_lookups', None)
        hdr = bool(getattr(owner, '_bloom_active', False))
        self._generating = rendered if rendered is not None else True
        try:
            with self._scenePaths(rendered, walk):
                owner._reflection_lookups = {}
                owner.applyViewFrame(frame, gl=False)
                gathered = owner._walkPaths(fresh=True) if walk is not None else owner.frameGather()
                records = [record for record in owner.renderSet(view, gathered)
                           if not any(record[4] is path for path in paths)]
                owner.captureBackground(view)
                owner.setupViewLighting(view, lighting, fitted=False)
                shader.use(lit=True)
                if hasattr(shader, 'set_hdr_output'):
                    shader.set_hdr_output(False)
                PBRMesh.reset_draw_state(owner)
                owner.shaderRenderOpaque(records, None)
                owner.shaderRenderTransparent(records, None)
        finally:
            self._generating = None
            PBRMesh.reset_draw_state(owner)
            shader.use(lit=True)
            if hasattr(shader, 'set_hdr_output'):
                shader.set_hdr_output(hdr)
            owner._reflection_lookups = lookups if lookups is not None else {}
            owner.clearPlanarReflection()
            if active is not None:
                owner.applyViewFrame(active, gl=False)
