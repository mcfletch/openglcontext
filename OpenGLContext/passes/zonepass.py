"""The render pass's side of zones: placing them, applying them, capturing them.

Mixed into :class:`~OpenGLContext.passes._flat.FlatPass`. Once a frame
:meth:`ZonesMixin.placeZones` places every :class:`~OpenGLContext.scenegraph.zone.Zone`
in the scene; for each view :meth:`ZonesMixin.setupZones` clears what the
last view left on the program; and for each draw :meth:`ZonesMixin.applyZones`
hands the PBR program the environment layers and the light mask the object's
zones give it, uploading only when they differ from the last draw's.

What each object gets is worked out by
:mod:`OpenGLContext.passes.zonelayers` and kept per object until the object or
a zone moves, a probe finishes a capture or the lights change, so a still
scene pays a dictionary lookup per draw. A scene with no zones pays one test.

:meth:`ZonesMixin.renderZoneProbes` draws the captures zones ask for
(:mod:`OpenGLContext.passes.zoneprobes`), before any view is drawn.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Hashable, List, Optional, Sequence, Tuple

import numpy as np

from OpenGLContext import renderoptions
from OpenGLContext.passes import zonelayers
from OpenGLContext.passes.disposal import PassResources, let_go
from OpenGLContext.passes.zonelayers import NO_ENVIRONMENT, SCENE_PROBE, ZonePack
from OpenGLContext.passes.zoneprobes import FACES_PER_FRAME, CaptureSchedule, CaptureTarget
from OpenGLContext.scenegraph import zone as zonenodes
from OpenGLContext.scenegraph.imagebasedlight import ImageBasedLight
from OpenGLContext.scenegraph.zone import (
    AUDIO, ENVIRONMENT, LIGHTS, MIRRORS, REVERB, VISIBILITY, PlacedZone,
    ZoneVisibility,
)

log = logging.getLogger(__name__)

__all__ = ['ZonesMixin']

#: The half-size of the box an object with no bounds is taken to fill: large
#: enough to cross every zone, so it is weighted per fragment.
_UNBOUNDED = 1.0e7


class _ObjectZones:
    """What one object was last worked out to get from the zones.

    ``centre`` and ``radius`` are the object's bounding sphere in the world
    when it was classified, and ``slack`` how far that sphere may move before
    any zone could see it differently; ``version`` is the pass's probe version
    ``pack`` was made at.
    """

    __slots__ = ('matrix', 'epoch', 'cell', 'kept', 'reach', 'mask', 'layers', 'pack',
                 'local', 'radius', 'centre', 'slack', 'version', 'lights', 'slots')

    def __init__(self, matrix: Any, epoch: int, cell: Tuple[int, ...],
                 kept: List[Any], reach: Optional[zonelayers.Reach], mask: int) -> None:
        self.matrix = matrix
        self.epoch = epoch
        self.cell = cell
        #: Every zone reaching the object, before the shader's limit.
        self.kept = kept
        self.reach = reach
        self.mask = mask
        self.layers: Tuple[float, ...] = ()
        self.pack: Optional[ZonePack] = None
        #: The bounding sphere's centre in the object's own frame, homogeneous.
        self.local: Optional[np.ndarray] = None
        self.radius = 0.0
        self.centre: Optional[Tuple[float, float, float]] = None
        self.slack = 0.0
        self.version = -1
        #: :func:`~OpenGLContext.passes.zonelayers.light_decision`, and the
        #: slot version ``mask`` was made for.
        self.lights: Any = (frozenset(), False)
        self.slots = -1


class _GroupBox:
    """The world box round an instanced group's members, as bounds to classify."""

    __slots__ = ('points',)

    def __init__(self, low: np.ndarray, high: np.ndarray) -> None:
        from OpenGLContext.scenegraph.zones import _corners
        self.points = np.concatenate([_corners(low, high), np.ones((8, 1))], axis=1)

    def getPoints(self) -> np.ndarray:
        return self.points


class ZonesMixin(PassResources):
    """Zones for a render pass; see the module docstring."""

    if False:  # pragma: no cover - attributes the pass supplies
        paths: Dict[type, List[Any]]
        shader_program: Any
        _ibl_probe: Any
        activeFrame: Any
        view: Any
        visiblePlacements: Any
        matrix: Any
        _reflection_lookups: Dict[Any, Any]

        def applyViewFrame(self, frame: Any, gl: bool = True) -> None: ...
        def renderSet(self, matrix: Any, gathered: Any) -> List[Any]: ...
        def setupViewLighting(self, view: Any, lighting: Any,
                              fitted: bool = True) -> None: ...
        def shaderRenderOpaque(self, records: Any, frustum: Any) -> Any: ...
        def clearPlanarReflection(self) -> None: ...
        def currentBackground(self) -> Any: ...

    #: Every zone this frame, placed.
    _zones: List[PlacedZone] = []
    #: The zones with an environment setting, and those with a lights one.
    _environmentZones: List[PlacedZone] = []
    _lightZones: List[PlacedZone] = []
    #: Each light a zone names, by id, with the zones naming it.
    _controlledLights: Dict[int, List[PlacedZone]] = {}
    #: Bumped whenever what an object's zones give it may have changed.
    _zoneEpoch = 0
    #: What each object was last worked out to get, by id of its path.
    _zoneObjects: Optional[Dict[int, '_ObjectZones']] = None
    #: Each zone's placement, reused while the zone has not moved.
    _zonePlacements: Optional[Dict[int, Any]] = None
    _zoneKeys: Tuple[int, ...] = ()
    #: What the program was last handed, so a run of alike draws uploads once.
    _zoneApplied: Any = None
    _lightsOffApplied = 0
    #: The light node bound to each slot, in slot order, for the light mask.
    boundLights: List[Any] = []
    _boundLightKeys: Tuple[int, ...] = ()
    #: The camera the current view looks from, in the world.
    _zoneCamera: Optional[np.ndarray] = None
    #: Captures of zone probes, and the target they are drawn into.
    _zoneCaptures: Optional[CaptureSchedule] = None
    _captureTarget: Optional[CaptureTarget] = None
    #: The zone whose probe is being drawn, while it is.
    _zoneCapturing: Any = None
    _zoneLighting: Any = None
    _probeLost = 0
    #: Image-based lights given a layer, by id, until each has been uploaded.
    _imageLights: Dict[int, Any] = {}
    #: What the scene's own image-based light was last uploaded against.
    _sceneLightMark: Any = None
    _zoneWarned = False
    #: The environment zones stacked for testing all at once, remade when the
    #: zones move.
    _environmentTable: Optional[zonelayers.ZoneTable] = None
    #: Every zone an object's classification depends on, for its slack.
    _slackTable: Optional[zonelayers.ZoneTable] = None
    #: Bumped whenever a probe layer's answer may have changed: a capture or
    #: an upload finishing, a capture starting or ending, a probe lost, the
    #: environment mode changing. A draw re-reads its layers only then.
    _probeVersion = 0
    _probeSignature: Any = None
    #: Instanced groups' boxes, by their members' paths, with the member
    #: matrices each was made from.
    _zoneGroups: Optional[Dict[Tuple[int, ...], Tuple[Any, Any, Any]]] = None
    #: Bumped when lights are bound to different slots.
    _slotVersion = 0
    #: The camera's cell for the view being drawn.
    _zoneCell: Tuple[int, ...] = ()
    _tableKeys: Tuple[int, ...] = ()

    def disposeResources(self) -> None:
        """Release the target zone probes are captured into."""
        let_go(self, '_captureTarget')
        super().disposeResources()

    # -- once a frame --------------------------------------------------------
    def placeZones(self) -> List[PlacedZone]:
        """Place every zone in the scene for this frame, and return them."""
        if self._zonePlacements is None:
            self._zonePlacements = {}
        found = []
        for path in self.paths.get(zonenodes.Zone, ()):
            if getattr(path, 'broken', False):
                continue
            found.append((path[-1], path.transformMatrix()))
        placed = zonenodes.placed_zones(found, self._zonePlacements)
        keys = tuple(id(zone) for zone in placed)
        if keys != self._zoneKeys:
            self._zoneKeys = keys
            alive = {id(zone.zone) for zone in placed}
            for key in [key for key in self._zonePlacements if key not in alive]:
                del self._zonePlacements[key]
            if self._zoneCaptures is not None:
                self._zoneCaptures.keep(alive)
            self._zoneEpoch += 1
        self._zones = placed
        self._environmentZones = [z for z in placed if z.setting(ENVIRONMENT) is not None]
        if keys != self._tableKeys:
            self._tableKeys = keys
            self._environmentTable = zonelayers.ZoneTable(self._environmentZones)
            self._allTable = zonelayers.ZoneTable(placed)
            self._slackTable = zonelayers.ZoneTable(
                [z for z in placed if z.setting(ENVIRONMENT) is not None
                 or z.setting(LIGHTS) is not None])
        self._lightZones = [z for z in placed if z.setting(LIGHTS) is not None]
        self._controlledLights = zonelayers.controlled_lights(placed)
        return placed

    #: Every zone, stacked for weighing all at once at one point.
    _allTable: Optional[zonelayers.ZoneTable] = None

    @property
    def zoneTable(self) -> Optional[zonelayers.ZoneTable]:
        """This frame's zones as a :class:`~OpenGLContext.passes.zonelayers.ZoneTable`."""
        return self._allTable

    @property
    def zones(self) -> List[PlacedZone]:
        """The zones placed for this frame."""
        return self._zones

    # -- once a view ---------------------------------------------------------
    def setupZones(self, matrix: Any) -> None:
        """Start a view: nothing is applied, and the camera is ``matrix``'s."""
        shader = self.shader_program
        self._zoneApplied = None
        self._lightsOffApplied = 0
        try:
            self._zoneCamera = np.linalg.inv(np.asarray(matrix, 'd'))[3, :3]
        except np.linalg.LinAlgError:
            self._zoneCamera = None
        self._zoneCell = self._cameraCell()
        self._nearness = None
        # Objects stream in and out of a large world, and what the dead ones
        # were given is let go of wholesale; the living are classified again.
        for kept in (self._zoneObjects, self._zoneGroups):
            if kept is not None and len(kept) > self.KEPT_LIMIT:
                kept.clear()
        keys = tuple(id(light) for light in self.boundLights)
        if keys != self._boundLightKeys:
            # Which light is in which slot decides the mask and nothing else,
            # so the objects keep their zones and only remake their masks.
            self._boundLightKeys = keys
            self._slotVersion += 1
        if shader is None:
            return
        if hasattr(shader, 'set_zones'):
            shader.set_zones(None)
        if hasattr(shader, 'set_lights_off'):
            shader.set_lights_off(0)

    # -- once a draw ---------------------------------------------------------
    def zoneState(self, path: Any, tmatrix: Any, bvolume: Any
                  ) -> Tuple[Optional[ZonePack], int]:
        """The environment layers and light mask the zones give one object.

        Which zones reach the object is kept until a zone moves or the object
        moves further than its slack -- the distance its bounding sphere had
        to the nearest zone edge when it was classified -- so a car driving
        down the middle of a forest zone is classified again only as it nears
        the next one. An object crossing more zones than the shader holds has
        its nearest ones chosen again as the camera moves a cell. The arrays
        are packed again only when the pass's probe version has moved on and
        a probe the object reads has changed.
        """
        if not self._environmentZones and not self._controlledLights and not self._lightZones:
            return None, 0
        objects = self._zoneObjects
        if objects is None:
            objects = self._zoneObjects = {}
        held = objects.get(id(path))
        if held is None or not self._current(held, tmatrix):
            self._classify([(path, tmatrix, bvolume)])
            held = objects[id(path)]
        if held.slots != self._slotVersion:
            held.slots = self._slotVersion
            held.mask = (zonelayers.light_mask(held.lights, self.boundLights,
                                               self._controlledLights)
                         if self._controlledLights or self._lightZones else 0)
        if held.reach is not None and held.reach.limited:
            cell = self._zoneCell
            if cell != held.cell:
                held.cell = cell
                held.reach = zonelayers.chosen(held.kept, self._zoneCamera,
                                               self._zoneWarn, self._environmentTable,
                                               self._cameraNearness())
                held.pack = None
        if held.reach is None:
            return None, held.mask
        if held.pack is None or held.version != self._probeVersion:
            layers = zonelayers.probe_layers(held.reach, self.zoneProbeLayer)
            if held.pack is None or layers != held.layers:
                held.layers = layers
                held.pack = zonelayers.pack_reach(held.reach, layers)
            held.version = self._probeVersion
        return held.pack, held.mask

    def _current(self, held: Optional['_ObjectZones'], tmatrix: Any) -> bool:
        """Whether ``held`` still answers for an object now placed by ``tmatrix``."""
        if held is None or held.epoch != self._zoneEpoch:
            return False
        if held.matrix is tmatrix:
            return True
        centre = held.centre
        if centre is None or held.slack <= 0.0:
            return False
        # The sphere is centred on the object's origin, so how far it moved is
        # how far the origin did: three numbers, and no matrix product.
        row = tmatrix[3]
        dx, dy, dz = float(row[0]) - centre[0], float(row[1]) - centre[1], \
            float(row[2]) - centre[2]
        if dx * dx + dy * dy + dz * dz > held.slack * held.slack:
            return False
        held.matrix = tmatrix
        return True

    def refreshZones(self, records: Sequence[Any]) -> None:
        """Classify, together, every record about to be drawn whose zones are stale.

        A still object keeps what it was given, and so does one that has not
        moved past its slack, so what is left here is the objects that moved
        near an edge -- and they are classified against every zone in one
        pass (:meth:`~OpenGLContext.passes.zonelayers.ZoneTable.classify_many`)
        rather than a numpy call apiece. Called once for each draw list, before
        the draws ask for their zones one at a time.
        """
        if not self._environmentZones and not self._lightZones:
            return
        objects = self._zoneObjects
        if objects is None:
            objects = self._zoneObjects = {}
        epoch = self._zoneEpoch
        found = objects.get
        current = self._current
        stale = []
        for record in records:
            held = found(id(record[4]))
            if held is not None and held.matrix is record[2] and held.epoch == epoch:
                continue                        # the common case, inline
            if not current(held, record[2]):
                stale.append((record[4], record[2], record[3]))
        if stale:
            self._classify(stale)

    def _classify(self, items: Sequence[Tuple[Any, Any, Any]]) -> None:
        """Classify ``(path, matrix, bounds)`` items against the zones, all at once."""
        objects = self._zoneObjects
        if objects is None:
            objects = self._zoneObjects = {}
        boxes = self._worldBoxes([(matrix, bounds) for _path, matrix, bounds in items])
        minimums = np.array([box[0] for box in boxes])
        maximums = np.array([box[1] for box in boxes])
        table = self._environmentTable
        reached = (table.classify_many(minimums, maximums)
                   if table is not None and self._environmentZones
                   else [[] for _ in items])
        spheres = [self._sphere(matrix, bounds) for _path, matrix, bounds in items]
        slack = np.zeros(len(items))
        bounded = [(index, sphere) for index, sphere in enumerate(spheres)
                   if sphere is not None]
        if bounded and self._slackTable is not None:
            slack[[index for index, _sphere in bounded]] = self._slackTable.sphere_slack(
                [sphere[2] for _index, sphere in bounded],
                [sphere[1] for _index, sphere in bounded])
        cell = self._zoneCell
        lit = bool(self._controlledLights or self._lightZones)
        for index, ((path, matrix, _bounds), reaching) in enumerate(zip(items, reached, strict=True)):
            kept = zonelayers.stacked(reaching)
            found = zonelayers.chosen(kept, self._zoneCamera, self._zoneWarn, table,
                                      self._cameraNearness() if len(kept) > zonelayers.MAX_ZONE_LAYERS
                                      else None)
            held = _ObjectZones(matrix, self._zoneEpoch, cell, kept, found, 0)
            if lit:
                held.lights = zonelayers.light_decision(
                    self._lightZones, minimums[index], maximums[index])
                held.mask = zonelayers.light_mask(held.lights, self.boundLights,
                                                  self._controlledLights)
            held.slots = self._slotVersion
            sphere = spheres[index]
            if sphere is not None:
                held.local, held.radius, held.centre = sphere
                held.slack = float(slack[index])
            objects[id(path)] = held

    def _worldBoxes(self, items: Sequence[Tuple[Any, Any]]) -> List[Tuple[np.ndarray, np.ndarray]]:
        """:meth:`worldBox` for many ``(matrix, bounds)``, the eight-cornered in one product."""
        boxes: List[Any] = [None] * len(items)
        corners, matrices, where = [], [], []
        for index, (matrix, bounds) in enumerate(items):
            try:
                points = bounds.getPoints() if bounds is not None else ()
            except Exception:
                points = ()
            if points is not None and len(points) == 8 and np.shape(points)[-1] == 4:
                corners.append(points)
                matrices.append(matrix)
                where.append(index)
            else:
                boxes[index] = self.worldBox(matrix, bounds)
        if where:
            world = np.einsum('mci,mij->mcj', np.asarray(corners, dtype='d'),
                              np.asarray(matrices, dtype='d'))[..., :3]
            lows, highs = world.min(axis=1), world.max(axis=1)
            for slot, index in enumerate(where):
                boxes[index] = (lows[slot], highs[slot])
        return boxes

    @staticmethod
    def _sphere(matrix: Any, bounds: Any) -> Optional[Tuple[None, float, Tuple[float, float, float]]]:
        """A sphere about the object's origin holding its bounds, however it turns.

        Returned as ``(None, radius, centre)``: centred on the origin rather
        than on the bounds, so telling whether the object has moved out of it
        takes the origin alone (:meth:`_current`).
        """
        try:
            points = bounds.getPoints() if bounds is not None else ()
        except Exception:
            return None
        if points is None or not len(points):
            return None
        local = np.asarray(points, dtype='d')[:, :3]
        m = np.asarray(matrix, dtype='d')
        scale = float(np.linalg.norm(m[:3, :3], axis=1).max())
        radius = float(np.linalg.norm(local, axis=1).max()) * scale
        origin = m[3, :3]
        return None, radius, (float(origin[0]), float(origin[1]), float(origin[2]))

    def _classifyObject(self, tmatrix: Any, bvolume: Any) -> '_ObjectZones':
        """One object classified on its own, as :meth:`_classify` would."""
        key = ('single', id(tmatrix))
        self._classify([(key, tmatrix, bvolume)])
        assert self._zoneObjects is not None
        return self._zoneObjects.pop(id(key))

    #: How many objects' zones are kept before the record is started afresh.
    KEPT_LIMIT = 50000

    #: How far the camera moves, in metres, before an object crossing more
    #: zones than the shader holds has its nearest zones chosen again.
    CAMERA_CELL = 32.0

    #: Every environment zone's distance from this view's camera, made the
    #: first time an object crossing too many zones asks.
    _nearness: Optional[Dict[int, float]] = None

    def _cameraNearness(self) -> Optional[Dict[int, float]]:
        if self._nearness is None and self._zoneCamera is not None \
                and self._environmentTable is not None:
            self._nearness = self._environmentTable.nearness(self._zoneCamera)
        return self._nearness

    def _cameraCell(self) -> Tuple[int, ...]:
        camera = self._zoneCamera
        if camera is None:
            return ()
        return tuple(int(v) for v in np.floor(np.asarray(camera) / self.CAMERA_CELL))

    def applyZones(self, shader: Any, path: Any, tmatrix: Any, bvolume: Any,
                   program: Any = None) -> None:
        """Hand the program the zones reaching the object about to be drawn."""
        if not self._zones:
            return
        objects = self._zoneObjects
        held = objects.get(id(path)) if objects is not None else None
        if (held is not None and held.matrix is tmatrix and held.epoch == self._zoneEpoch
                and held.version == self._probeVersion and held.slots == self._slotVersion
                and (held.pack is not None or held.reach is None)
                and not (held.reach is not None and held.reach.limited
                         and held.cell != self._zoneCell)):
            # The common case -- an object that has not moved since its zones
            # were packed -- in as few steps as it can be.
            pack, mask = held.pack, held.mask
        else:
            pack, mask = self.zoneState(path, tmatrix, bvolume)
        key = None if pack is None else pack.key
        if key is not self._zoneApplied and key != self._zoneApplied:
            setter = getattr(shader, 'set_zones', None)
            if setter is not None:
                setter(pack, program=program)
            self._zoneApplied = key
        if mask != self._lightsOffApplied:
            setter = getattr(shader, 'set_lights_off', None)
            if setter is not None:
                setter(mask, program=program)
            self._lightsOffApplied = mask

    def applyZonesToGroup(self, shader: Any, members: Sequence[Any],
                          program: Any = None) -> None:
        """Hand the program the zones reaching any member of an instanced group.

        The group draws as one, so it takes the zones reaching the box around
        all of its members; per fragment, each member is weighted where it
        stands.
        """
        if not self._zones:
            return
        if not members:
            return
        if len(members) == 1:
            record = members[0]
            self.applyZones(shader, record[4], record[2], record[3], program)
            return
        groups = self._zoneGroups
        if groups is None:
            groups = self._zoneGroups = {}
        key = tuple(id(record[4]) for record in members)
        placed = tuple(id(record[2]) for record in members)
        held = groups.get(key)
        if held is None or held[0] != placed:
            # A member moved, or the group is new: the box round all of them,
            # as the bounds of one object placed where it already is.
            boxes = self._worldBoxes([(record[2], record[3]) for record in members])
            low = np.min([box[0] for box in boxes], axis=0)
            high = np.max([box[1] for box in boxes], axis=0)
            held = (placed, _GroupBox(low, high), np.identity(4))
            groups[key] = held
        _placed, box, where = held
        pack, mask = self.zoneState(box, where, box)
        self._applyZoneState(shader, pack, mask, program)

    def _applyZoneState(self, shader: Any, pack: Optional[ZonePack], mask: int,
                        program: Any) -> None:
        key = None if pack is None else pack.key
        if key != self._zoneApplied:
            setter = getattr(shader, 'set_zones', None)
            if setter is not None:
                setter(pack, program=program)
            self._zoneApplied = key
        if mask != self._lightsOffApplied:
            setter = getattr(shader, 'set_lights_off', None)
            if setter is not None:
                setter(mask, program=program)
            self._lightsOffApplied = mask

    @staticmethod
    def worldBox(tmatrix: Any, bvolume: Any) -> Tuple[np.ndarray, np.ndarray]:
        """The world-space box around an object's bounds, or a vast one without."""
        try:
            points = bvolume.getPoints() if bvolume is not None else ()
        except Exception:
            points = ()
        if points is None or not len(points):
            big = np.full(3, _UNBOUNDED)
            return -big, big
        local = np.asarray(points, dtype='d')
        if local.shape[-1] == 3:
            local = np.concatenate([local, np.ones((len(local), 1))], axis=-1)
        world = (local @ np.asarray(tmatrix, dtype='d'))[:, :3]
        return world.min(axis=0), world.max(axis=0)

    def _zoneWarn(self, message: str) -> None:
        """Say once, for the pass, that an object crosses more zones than it can take."""
        if not self._zoneWarned:
            self._zoneWarned = True
            log.info('zones: %s; objects this large are given the zones nearest '
                     'the camera, chosen again as it moves', message)

    # -- probes --------------------------------------------------------------
    def zoneProbeLayer(self, zone: PlacedZone) -> float:
        """Which probe layer ``zone``'s environment reads this frame.

        The scene's own environment for a zone that captures nothing, or
        whose capture cannot be read here -- the probe is not an array, or
        the environment is not the ``full`` probe. A capturing zone is asked
        for here, since this is where the pass learns something it lights is
        being drawn; until its first capture it reads the scene's
        environment, except inside that capture, where it reads none.
        """
        setting = zone.setting(ENVIRONMENT)
        light = getattr(setting, 'light', None) if setting is not None else None
        if isinstance(light, ImageBasedLight):
            return self._lightLayer(light)
        if setting is None or not bool(getattr(setting, 'capture', False)):
            return SCENE_PROBE
        probe = getattr(self, '_ibl_probe', None)
        lighting = self._zoneLighting
        if probe is None or not probe.arrayed or lighting is None or lighting[0] != 'full':
            return SCENE_PROBE
        schedule = self._zoneCaptures
        if schedule is None:
            schedule = self._zoneCaptures = CaptureSchedule()
        key = id(zone.zone)
        if schedule.request(key):
            # The capture is drawn at the start of a frame, so a context that
            # draws only when asked has to be asked for one.
            self._askForFrame()
        layer = schedule.layer(key)
        if layer is None:
            return NO_ENVIRONMENT if self._zoneCapturing is zone.zone else SCENE_PROBE
        return float(layer)

    def _lightLayer(self, light: Any) -> float:
        """The layer an image-based light is in, once it has been uploaded.

        Its layer is reserved the first time it is asked for, and filled at
        the start of the next frame (:meth:`uploadImageLights`); until then
        the zone reads the scene's environment.
        """
        probe = getattr(self, '_ibl_probe', None)
        lighting = self._zoneLighting
        if probe is None or not probe.arrayed or lighting is None or lighting[0] != 'full':
            return SCENE_PROBE
        schedule = self._zoneCaptures
        if schedule is None:
            schedule = self._zoneCaptures = CaptureSchedule()
        key = id(light)
        if schedule.reserve(key):
            self.__dict__.setdefault('_imageLights', {})[key] = light
            self._askForFrame()
        layer = schedule.layer(key)
        return SCENE_PROBE if layer is None else float(layer)

    def uploadImageLights(self, probe: Any) -> None:
        """Put every image-based light waiting for its layer into it, and the scene's into layer 0."""
        schedule = self._zoneCaptures
        if schedule is not None and schedule.layers > probe.layers:
            probe.grow(schedule.layers)
        if schedule is not None:
            for key, light in list(self._imageLights.items()):
                if schedule.layer(key) is not None:
                    continue
                layer = schedule.layer_of(key)
                if layer is None:
                    del self._imageLights[key]
                elif probe.upload_light(light, layer):
                    schedule.finished(key)
                    self._probeVersion += 1
        scene = self.sceneImageLight()
        mark = (id(scene), probe.lost, id(probe.prefilter))
        if scene is not None and mark != self._sceneLightMark:
            if probe.upload_light(scene, 0):
                self._sceneLightMark = mark

    def sceneImageLight(self) -> Any:
        """The image-based light the scene itself is lit by, or None."""
        for path in self.paths.get(ImageBasedLight, ()):
            if not getattr(path, 'broken', False):
                return path[-1]
        return None

    def zoneCaptureFaces(self) -> int:
        """How many faces of a zone's cube may be drawn in one frame."""
        return max(1, min(6, int(renderoptions.number(
            self, 'zoneCaptureFaces',
            renderoptions.env_number('OPENGLCONTEXT_ZONE_CAPTURE_FACES',
                                     float(FACES_PER_FRAME))))))

    def renderZoneProbes(self, frames: Sequence[Any], lighting: Any) -> None:
        """Draw this frame's share of the zone captures, before any view is drawn."""
        self._zoneLighting = lighting
        probe = getattr(self, '_ibl_probe', None)
        signature = (None if lighting is None else lighting[0], id(probe),
                     None if probe is None else (probe.arrayed, probe.ready))
        if signature != self._probeSignature:
            self._probeSignature = signature
            self._probeVersion += 1
        schedule = self._zoneCaptures
        probe = getattr(self, '_ibl_probe', None)
        if probe is not None and schedule is None and self.sceneImageLight() is not None \
                and lighting is not None and lighting[0] == 'full' and probe.ready:
            self.uploadImageLights(probe)
        if schedule is None or probe is None or not probe.arrayed:
            return
        if lighting is None or lighting[0] != 'full' or not probe.ready:
            return
        if probe.lost != self._probeLost:
            self._probeLost = probe.lost
            schedule.lost()
            self._probeVersion += 1
            self.__dict__.setdefault('_imageLights', {}).update(self._everyImageLight())
        self.uploadImageLights(probe)
        camera = self._frameCamera(frames)
        if camera is not None:
            for placed in self._environmentZones:
                setting = placed.setting(ENVIRONMENT)
                if bool(getattr(setting, 'capture', False)) and placed.weight(camera) >= 1.0:
                    schedule.camera_inside(id(placed.zone))
        by_key: Dict[Hashable, PlacedZone] = {
            id(zone.zone): zone for zone in self._environmentZones}
        key = schedule.next(lambda k: self._captureDistance(by_key.get(k), camera))
        if key is None:
            return
        zone = by_key.get(key)
        if zone is None:
            return
        if schedule.layers > probe.layers:
            probe.grow(schedule.layers)
            if probe.lost != self._probeLost:
                self._probeLost = probe.lost
                schedule.lost()
                self._probeVersion += 1
            self._probeVersion += 1
        faces = schedule.faces(key, self.zoneCaptureFaces())
        whole = self._drawCapture(zone, faces, frames, lighting)
        if whole is None:
            return
        if schedule.drawn(key, len(faces)):
            layer = schedule._captures[key].layer
            target = self._captureTarget
            if target is not None and target.cube is not None and probe.convolve(target.cube, layer):
                schedule.finished(key)
                self._probeVersion += 1
                log.info('zone %r captured into probe layer %d (capture %d)',
                         getattr(zone.zone, 'DEF', None) or key, layer,
                         schedule.captured(key))
        # The frame after this one draws what was captured, and the next
        # capture if one is waiting.
        self._askForFrame()

    def _everyImageLight(self) -> Dict[int, Any]:
        """Every zone's image-based light, by id, to upload again after a loss."""
        found = {}
        for zone in self._environmentZones:
            light = getattr(zone.setting(ENVIRONMENT), 'light', None)
            if isinstance(light, ImageBasedLight):
                found[id(light)] = light
        return found

    def _askForFrame(self) -> None:
        trigger = getattr(getattr(self, 'context', None), 'triggerRedraw', None)
        if trigger is not None:
            trigger(0)

    @staticmethod
    def _captureDistance(zone: Optional[PlacedZone], camera: Optional[np.ndarray]) -> float:
        if zone is None:
            return float('inf')
        if camera is None:
            return 0.0
        return max(0.0, float(zone.shape.distance(camera)))

    def _frameCamera(self, frames: Sequence[Any]) -> Optional[np.ndarray]:
        frame = self.activeFrame if self.activeFrame is not None else (frames[0] if frames else None)
        if frame is None:
            return None
        try:
            return np.linalg.inv(np.asarray(frame.modelView, 'd'))[3, :3]
        except np.linalg.LinAlgError:
            return None

    def _drawCapture(self, zone: PlacedZone, faces: Sequence[int],
                     frames: Sequence[Any], lighting: Any) -> Optional[bool]:
        """Draw ``faces`` of ``zone``'s cube; None where nothing could be drawn."""
        from OpenGLContext import frustum as frustummodule
        from OpenGLContext.multiview.strategy import ViewFrame
        from OpenGLContext.passes import shadowmath
        from OpenGLContext.scenegraph.pbrmesh import PBRMesh
        gathered = getattr(self, '_frameGather', None)
        template = self.activeFrame if self.activeFrame is not None else (frames[0] if frames else None)
        shader = self.shader_program
        if gathered is None or template is None or shader is None:
            return None
        probe = self._ibl_probe
        target = self._captureTarget
        if target is None or target.size != probe.ENV_SIZE:
            if target is not None:
                target.release()
            target = self._captureTarget = CaptureTarget(probe.ENV_SIZE)
        setting = zone.setting(ENVIRONMENT)
        centre = zone.to_world(getattr(setting, 'captureCentre', (0.0, 0.0, 0.0)))
        near, far = self._captureDepth(template)
        projection = shadowmath.cube_projection(near, far)
        active = self.activeFrame
        # A capture is seen from somewhere no mirror was drawn for, so the
        # mirrors in it show the probe rather than another view's reflection.
        lookups = getattr(self, '_reflection_lookups', None)
        self._reflection_lookups = {}
        self._zoneCapturing = zone.zone
        self._probeVersion += 1
        target.begin()
        try:
            for face in faces:
                view = shadowmath.cube_face_view(centre, face)
                modelproj = np.dot(view, projection)
                frame = ViewFrame(
                    template.view, template.camera, (0, 0, target.size, target.size),
                    view, projection, modelproj,
                    frustummodule.Frustum.fromViewingMatrix(modelproj, normalize=1),
                    fitted=False)
                self.applyViewFrame(frame, gl=False)
                records = [record for record in self.renderSet(view, gathered)
                           if not record[0][0]]
                target.face(face)
                self.captureBackground(view)
                self.setupViewLighting(view, lighting, fitted=False)
                shader.use(lit=True)
                shader.set_hdr_output(True)
                PBRMesh.reset_draw_state(self)
                self.shaderRenderOpaque(records, None)
            return True
        except Exception as err:
            log.error('zone capture failed: %s', err)
            self._zoneCaptures = None
            return None
        finally:
            target.end(whole=True)
            PBRMesh.reset_draw_state(self)
            shader.use(lit=True)
            shader.set_hdr_output(bool(getattr(self, '_bloom_active', False)))
            self._zoneCapturing = None
            self._probeVersion += 1
            self._reflection_lookups = lookups if lookups is not None else {}
            self.clearPlanarReflection()
            if active is not None:
                self.applyViewFrame(active, gl=False)

    @staticmethod
    def _captureDepth(template: Any) -> Tuple[float, float]:
        """The near and far planes of a capture, from the camera's own."""
        try:
            fovy, aspect, near, far = template.camera.frustum
            return max(float(near), 0.05), max(float(far), float(near) * 2.0)
        except (AttributeError, TypeError, ValueError):
            return 0.1, 1000.0

    def captureBackground(self, view: Any) -> None:
        """Draw the scene's background into a capture face looking along ``view``."""
        path = self.currentBackground()
        if path is None:
            return
        rotation = np.array(view, dtype='f')
        rotation[3, :3] = 0.0
        # As shaderBackgroundRender composes it, with the face's turn in
        # place of the camera's.
        self.matrix = np.dot(rotation,
                             path.transformMatrix(translate=0, scale=0, rotate=1))
        background = path[-1]
        if hasattr(background, 'RenderShader'):
            background.RenderShader(mode=self, clear=True)
        else:
            background.Render(mode=self, clear=True)

    # -- what the camera sees ------------------------------------------------
    #: The ids of the nodes zones hide from the view being culled.
    _zoneHidden: frozenset = frozenset()

    def zoneHiddenAt(self, point: Optional[Any]) -> frozenset:
        """The ids of the nodes the zones hide from a camera at ``point``.

        A node a ``ZoneVisibility`` shows is drawn only for a camera inside a
        zone showing it, and one it hides is drawn only for a camera outside
        every zone hiding it. Where several zones name one node, the one on
        top at the camera decides.
        """
        if point is None or not self._zones:
            return frozenset()
        named: Dict[int, List[Tuple[Tuple[int, float], bool, float]]] = {}
        for zone in self._zones:
            setting = zone.setting(VISIBILITY)
            if not isinstance(setting, ZoneVisibility) or not bool(setting.enabled):
                continue
            weight = zone.weight(point)
            for node in getattr(setting, 'nodes', None) or ():
                named.setdefault(id(node), []).append(
                    ((zone.priority, -zone.volume), bool(setting.visible), weight))
        if not named:
            return frozenset()
        hidden = set()
        for key, entries in named.items():
            inside = [entry for entry in entries if entry[2] > 0.0]
            if inside:
                shown = max(inside, key=lambda entry: entry[0])[1]
            else:
                shown = not max(entries, key=lambda entry: entry[0])[1]
            if not shown:
                hidden.add(key)
        return frozenset(hidden)

    def zoneVisible(self, path: Any) -> bool:
        """Whether no node of ``path`` is hidden from the view being culled."""
        hidden = self._zoneHidden
        if not hidden:
            return True
        return not any(id(node) in hidden for node in path)

    def mirrorsZoned(self) -> bool:
        """Whether any zone has a say over which mirrors draw a reflection."""
        return any(zone.setting(MIRRORS) is not None for zone in self._zones)

    def mirrorAllowed(self, record: Any, eye: Any) -> bool:
        """Whether a mirror's reflection may be drawn for a camera at ``eye``.

        A mirror a ``ZoneMirrors`` names draws its reflection only for a
        camera inside a zone naming it. Any other mirror draws its reflection
        except for a camera wholly inside a zone that switches mirrors off.
        """
        path = record[4]
        ids = {id(node) for node in path}
        candidates = []
        names: Dict[Any, List[Any]] = {}
        controlled = False
        for zone in self._zones:
            setting = zone.setting(MIRRORS)
            if setting is None:
                continue
            candidate = zone.candidate(MIRRORS, zone.weight(eye))
            candidates.append(candidate)
            if candidate[1] is not None:
                mine = [id(node) for node in getattr(setting, 'nodes', None) or ()
                        if id(node) in ids]
                if mine:
                    controlled = True
                    names[candidate[0]] = ['mirror']
        from OpenGLContext.scenegraph import zones as zonemath
        stack = zonemath.layers(candidates)
        if controlled:
            return zonemath.named_shares(stack, names).get('mirror', 0.0) > 0.0
        off = sum(layer.share for layer in stack if layer.block is None)
        return off < 1.0

    # -- the camera's zones --------------------------------------------------
    def cameraShares(self, key: str, point: Any, names: Any) -> Dict[Any, float]:
        """How much each thing zones switch on for ``key`` is on, seen from ``point``."""
        return zonelayers.camera_shares(self._zones, point, key, names)

    def zoneReverb(self, point: Any) -> zonelayers.Reverb:
        """The reverb heard at ``point``."""
        return zonelayers.reverb_at(self._zones, point)

    def zoneControlled(self, key: str, names: Any) -> set:
        """The ids of everything any zone names for ``key``."""
        found: set = set()
        for zone in self._zones:
            setting = zone.setting(key)
            if setting is None or not bool(setting.enabled):
                continue
            found.update(id(item) for item in names(setting))
        return found


#: Setting keys the camera decides, for the module's readers.
CAMERA_KEYS = (AUDIO, REVERB, VISIBILITY, MIRRORS)
