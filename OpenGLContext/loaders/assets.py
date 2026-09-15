"""The models a package ships: where they are, and how a caller asks for one.

A game's art is a table of names -- this weapon is that ``.glb``, that vehicle
is this one -- and everything else about loading it is the same every time.
:class:`AssetLibrary` is a directory of models addressed by relative name, so a
table of art is a table of filenames rather than a path built at each call site.

**A model that will not load is not an error.** It leaves a hand empty, a
pickup undrawn or a car drawn as whatever the caller falls back to, and the
program carries on: the rules of a game are what decide it, and a level that
fails to start over one corrupt file has failed worse than one with an
invisible car in it. The failure is logged, with its traceback, and
:meth:`AssetLibrary.shared` logs it once.

**Two ways to ask for one.** :meth:`AssetLibrary.load` reads the file and hands
back a scene nobody else holds, for a caller that will repaint or otherwise
change what it gets; :meth:`AssetLibrary.shared` hands back one copy to every
caller, for the far more common case of a model that is only drawn -- the same
subtree mounted under several parents, which is what a scenegraph's USE has
always meant.

What comes back is the whole
:class:`~OpenGLContext.loaders.gltf.scene.GLTFScene`: ``group`` is the subtree
to mount, ``getDEF`` finds a node by the name it was authored under,
``materials`` finds a material by its, and ``player_named`` finds an animation.
:func:`recolour` and :func:`brighten` paint a whole subtree, for art whose
colour is the whole of what it says.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Callable, Iterator, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext.loaders.gltf import load_gltf
from OpenGLContext.loaders.gltf.transforms import _local_matrix_rv

log = logging.getLogger(__name__)

__all__ = ["AssetLibrary", "bounds", "brighten", "merged_mesh", "recolour", "seated", "shapes"]


class AssetLibrary(object):
    """The models under one directory, addressed by relative name.

    ``root`` is where the art lives -- for a package that ships its own, the
    ``assets`` directory beside its modules::

        ART = AssetLibrary(os.path.join(os.path.dirname(__file__), 'assets'))
        scene = ART.shared('cars/saloon.glb')
        if scene is not None:
            world.children.append(scene.group)
    """

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        self._shared: dict[str, Optional[Any]] = {}
        self._variants: dict[Any, Optional[Any]] = {}

    def __repr__(self) -> str:
        return "AssetLibrary(%r)" % (self.root,)

    def path_for(self, relative: str) -> str:
        """Where a table's model name actually is on disk.

        A table names its models the way a reference is written, with ``/``
        between the parts; this is a path on the filesystem holding them, so the
        parts are rejoined with whatever separates a path here.
        """
        return os.path.join(self.root, *relative.split("/"))

    def load(self, relative: str) -> Optional[Any]:
        """Read one model and hand back a scene nobody else holds, or None.

        Every call reads the file again, so the caller is entitled to repaint,
        pose or otherwise change what it gets. Callers that only draw a model
        want :meth:`shared`.
        """
        try:
            return load_gltf(self.path_for(relative))
        except Exception:  # noqa: BLE001 - art, not rules
            log.warning("could not load the model %s", relative, exc_info=True)
            return None

    def shared(self, relative: str) -> Optional[Any]:
        """One copy of a model, for every caller that only draws it.

        The subtree comes back as it was authored and must be left that way:
        it is mounted in as many places as it has been asked for, and repainting
        it repaints all of them. A caller that means to change a model calls
        :meth:`load` instead.

        A model that will not load is remembered as absent, so a file that is
        missing is read for once rather than once a frame.
        """
        if relative not in self._shared:
            self._shared[relative] = self.load(relative)
        return self._shared[relative]

    def variant(
        self, relative: str, key: Any, prepare: Optional[Callable[[Any], Any]] = None
    ) -> Optional[Any]:
        """One copy of a model per ``key``, prepared once and then shared.

        Between :meth:`shared`, which is one copy of a model as it was authored,
        and :meth:`load`, which reads the file again for every caller that means
        to change what it gets. A crowd of the same model in a handful of
        colours wants neither: :meth:`shared` cannot be repainted without
        repainting all of it, and :meth:`load` costs a file read and a parse per
        member of the crowd -- on the frame that member appears.

        ``key`` names the version -- the colour, the team, the season -- and
        ``prepare(scene)`` makes it, called once, the first time that key is
        asked for. Everything asking for the same key afterwards gets that same
        scene, which is also what lets the renderer draw the crowd as one batch::

            scene = ART.variant('cars/saloon.glb', paint,
                                prepare=lambda one: recolour(one.group, paint))

        Since the scene is shared, a caller that changes it afterwards changes
        it for every other holder -- which is the same contract :meth:`shared`
        has. A model that will not load is remembered as absent, and ``prepare``
        is not called for one.
        """
        where = (relative, key)
        if where not in self._variants:
            scene = self.load(relative)
            if scene is not None and prepare is not None:
                prepare(scene)
            self._variants[where] = scene
        return self._variants[where]

    def clear(self) -> None:
        """Forget every shared copy and every variant, so the next call reads
        the files again."""
        self._shared.clear()
        self._variants.clear()


def shapes(node: Any) -> Iterator[Any]:
    """Every ``Shape`` in a subtree, in the order it was built."""
    if getattr(node, "geometry", None) is not None:
        yield node
    for child in getattr(node, "children", None) or ():
        yield from shapes(child)


def merged_mesh(node: Any) -> "Optional[Tuple[dict, np.ndarray]]":
    """A subtree's triangle meshes as one glTF-shaped mesh in world space.

    Returns ``({'POSITION': (v, 3), 'NORMAL': (v, 3)}, indices)``, or None where
    the subtree holds no triangles.

    A model is rarely one primitive. It is one per material, and one per 65,535
    vertices wherever an exporter wrote 16-bit indices -- a scan of half a
    million triangles arrives as twenty-five pieces that happen to touch. Work
    that asks about the *surface* rather than about the draw calls wants them
    back together: a decimator handed the pieces separately keeps a seam along
    every join, because neither side knows the other shares its edge.

    Positions and normals are brought into world space, so the pieces line up
    the way they are drawn. A primitive carrying no normals is given the
    surface's own, since anything measuring or shading the result needs them.

        from OpenGLContext.loaders.assets import merged_mesh
        from OpenGLContext.loaders.gltf import load_gltf

        attributes, indices = merged_mesh(load_gltf('scan.glb').group)
    """
    from OpenGLContext.loaders.gltf.meshes import estimate_normals

    positions: list = []
    normals: list = []
    triangles: list = []
    _merge(node, np.eye(4), positions, normals, triangles, (), [0])
    if not positions:
        return None
    merged = np.concatenate(positions).astype("f4")
    indices = np.concatenate(triangles).astype(np.uint32)
    together = np.concatenate(normals) if normals else None
    if together is None or len(together) != len(merged):
        together = estimate_normals(merged, indices)
    return {"POSITION": merged, "NORMAL": np.ascontiguousarray(together, dtype="f4")}, indices


def _merge(
    node: Any,
    world: np.ndarray,
    positions: list,
    normals: list,
    triangles: list,
    ancestry: Tuple[int, ...],
    offset: list,
) -> None:
    """Append one subtree's world-space vertices and triangles to the lists."""
    from OpenGLContext.loaders.gltf.meshes import estimate_normals

    # Cycle-detect on the path rather than globally: one mesh mounted under
    # several transforms is several instances, and each belongs at its own.
    if id(node) in ancestry:
        return
    ancestry = ancestry + (id(node),)
    if (
        hasattr(node, "translation")
        or hasattr(node, "rotation")
        or getattr(node, "_forward", None) is not None
    ):
        try:
            world = np.asarray(_local_matrix_rv(node), dtype="d") @ world
        except Exception:
            log.warning(
                "%r has a pose that does not resolve; merged at its parent", node, exc_info=True
            )
    geometry = getattr(node, "geometry", None)
    mesh = _triangle_arrays(geometry)
    if mesh is not None:
        points, faces, given = mesh
        placed = np.column_stack([points, np.ones(len(points))]) @ world
        positions.append(placed[:, :3])
        if given is None:
            given = estimate_normals(points, faces)
        # Normals are directions: the translation must not reach them, and a
        # scaled transform would need its inverse transpose. Renormalising is
        # what keeps a uniformly-scaled model's shading right either way.
        turned = np.asarray(given, dtype="d") @ world[:3, :3]
        lengths = np.linalg.norm(turned, axis=1)
        turned[lengths > 0] /= lengths[lengths > 0][:, None]
        normals.append(turned)
        triangles.append(np.asarray(faces).reshape(-1) + offset[0])
        offset[0] += len(points)
    for child in getattr(node, "children", None) or ():
        _merge(child, world, positions, normals, triangles, ancestry, offset)


def _triangle_arrays(geometry: Any) -> Any:
    """``(positions, indices, normals-or-None)`` of an indexed triangle mesh."""
    from OpenGL.GL import GL_TRIANGLES

    points = getattr(geometry, "positions", None)
    faces = getattr(geometry, "indices", None)
    if points is None or faces is None or not len(faces):
        return None
    if getattr(geometry, "draw_mode", GL_TRIANGLES) != GL_TRIANGLES:
        return None
    return np.asarray(points), np.asarray(faces).reshape(-1), getattr(geometry, "normals", None)


def brighten(node: Any, glow: float) -> int:
    """Light a subtree from inside without repainting it; returns materials touched.

    Each material glows in **its own** colour, so a model keeps its reds red and
    its greys grey rather than being pulled towards one hue. It is a floor under
    the lighting, not a light: it touches this model and nothing else in the
    world, which is what a model in a scene that places no lights of its own
    needs to be visible at all.
    """
    amount = float(glow)
    touched = 0
    for material in _materials(node):
        own: Any = getattr(material, "baseColor", None)
        if own is None:
            own = getattr(material, "diffuseColor", (1.0, 1.0, 1.0))
        lit = tuple(float(value) * amount for value in own)
        if hasattr(material, "emissiveColor"):
            material.emissiveColor = lit
        touched += 1
    return touched


def recolour(node: Any, colour: Sequence[float], glow: float = 0.0) -> int:
    """Repaint a subtree in one colour; returns how many materials were touched.

    **Mutates what it is given**, so it belongs to a subtree from
    :meth:`AssetLibrary.load` rather than to a shared one. One model painted
    several ways is what makes a family of pickups, or a road full of cars, one
    file rather than one file each.

    Only the base and emissive colours move. Transparency, alpha mode, metallic,
    roughness, transmission and the rest are the model's own, and are what make
    glass read as glass: a repaint that flattened those would leave every
    variant looking like the same plastic. A model with more than one material
    that should keep them apart is repainted through its own named material --
    ``scene.materials['paint']`` -- rather than through this.

    ``glow`` is a fraction of the colour added as emission, as in
    :func:`brighten`.
    """
    wanted = tuple(float(value) for value in colour)
    lit = tuple(value * float(glow) for value in wanted)
    touched = 0
    for material in _materials(node):
        for name, value in (
            ("baseColor", wanted),
            ("diffuseColor", wanted),
            ("emissiveColor", lit),
        ):
            if hasattr(material, name):
                setattr(material, name, value)
        touched += 1
    return touched


def bounds(node: Any) -> "Optional[Tuple[np.ndarray, np.ndarray]]":
    """The box a subtree occupies, as ``(minimum, maximum)``, or None if empty.

    In the space the subtree's own root sits in, with every ``Transform`` on the
    way down applied -- so what comes back is where the geometry actually is,
    not where it was authored. What a caller does with it is usually to cut a
    collider from a model, to seat it on the ground (:func:`seated`), or to
    check that a model is the size it was meant to be; none of those wants a GL
    context, and this needs none.

    Geometry that carries its shape as numbers -- a VRML ``Cone``, a ``Sphere``
    -- is measured by the box it declares rather than by a vertex array it does
    not have, so a subtree of primitives measures the same as one of meshes.
    """
    boxes: list = []
    _measure(node, np.eye(4), boxes)
    if not boxes:
        return None
    stacked = np.asarray(boxes, dtype="d")
    return stacked[:, 0].min(axis=0), stacked[:, 1].max(axis=0)


def seated(node: Any, sink: float = 0.0) -> Any:
    """``node`` wrapped so that its underside sits at the wrapper's origin.

    Placing a model puts *its origin* where the caller asked, which reads as
    "on the ground" only for art authored with its feet there. A VRML primitive
    is centred on its origin, and a model exported from a modelling package sits
    wherever its author left it, so the same placement drops one into the hill
    and floats the next above it. This measures what the subtree occupies and
    lifts it by its own underside, which makes the origin the point the thing
    stands on.

    ``sink`` is how far *back* into the ground to settle it, in the units the
    subtree is modelled in -- what a tree's root flare or a boulder's base wants
    so that it meets the ground rather than perching on it.

    The wrapper is a new node and ``node`` is not touched, so one prototype
    seats into as many scatters as a caller likes. A subtree with nothing to
    measure comes back unchanged: there is no underside to find, and refusing to
    place it would be a worse answer than placing it where it was asked for.
    """
    measured = bounds(node)
    if measured is None:
        return node
    lift = -float(measured[0][1]) - float(sink)
    from OpenGLContext.scenegraph.transform import Transform

    return Transform(translation=[0.0, lift, 0.0], children=[node])


def _measure(node: Any, parent: np.ndarray, boxes: list) -> None:
    """Accumulate one subtree's world-space boxes into ``boxes``."""
    # Row-vector convention, as the renderer and the glTF loader both use:
    # p_world = p_local @ local @ parent.
    world = (
        _local_matrix_rv(node) @ parent
        if getattr(node, "translation", None) is not None
        else parent
    )
    local = _local_points(getattr(node, "geometry", None))
    if local is not None:
        placed = np.column_stack([local, np.ones(len(local))]) @ world
        boxes.append((placed[:, :3].min(axis=0), placed[:, :3].max(axis=0)))
    for child in getattr(node, "children", None) or ():
        _measure(child, world, boxes)


def _local_points(geometry: Any) -> "Optional[np.ndarray]":
    """Points spanning a geometry's own extent, in its own space, or None.

    A vertex array where there is one, and otherwise the corners of the box the
    geometry declares -- which is how a node that is a handful of numbers
    (``Cone``, ``Sphere``, ``Text``) says how big it is. The corners bound the
    same space the vertices would, which is all a box is asked for.
    """
    if geometry is None:
        return None
    points = getattr(geometry, "positions", None)
    if points is None:
        points = getattr(getattr(geometry, "coord", None), "point", None)
    if points is not None and len(points):
        return np.asarray(points, dtype="d").reshape(-1, 3)
    volume = getattr(geometry, "boundingVolume", None)
    if volume is None:
        return None
    try:
        # No render pass to ask, so this is only the geometry that can answer
        # from its own fields; one that needs the pass (a cache, a font) says so
        # by raising, and contributes nothing rather than stopping the measure.
        corners = np.asarray(volume(None).getPoints(), dtype="d")
    except Exception:
        return None
    return corners.reshape(-1, corners.shape[-1])[:, :3] if len(corners) else None


def _materials(node: Any) -> Iterator[Any]:
    """The material of every shape in a subtree that has one."""
    for shape in shapes(node):
        material = getattr(getattr(shape, "appearance", None), "material", None)
        if material is not None:
            yield material
