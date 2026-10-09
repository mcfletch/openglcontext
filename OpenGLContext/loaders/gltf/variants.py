"""KHR_materials_variants: named sets of materials a document can be drawn in.

A document lists its variants by name; each primitive maps some of them to a
material of its own. :class:`MaterialVariants` holds the names and every
primitive that maps one, and :meth:`MaterialVariants.select` dresses each of
those primitives in its material for the variant, or in its own material where
it maps none. One variant is active at a time, or none::

    scene = load_gltf('shoe.glb')
    scene.variants                  # ('midnight', 'beach', 'street')
    scene.select_variant('beach')
    scene.select_variant(None)      # back to each primitive's own material

The mesh keeps what it was given as :attr:`PBRMesh.materialVariants`, a
:class:`PrimitiveVariants`, so the writer puts the same mappings back.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional, Sequence, Union

__all__ = ['EXTENSION', 'PrimitiveVariants', 'MaterialVariants',
           'variant_names', 'primitive_mappings']

log = logging.getLogger(__name__)

EXTENSION = 'KHR_materials_variants'


@dataclass
class PrimitiveVariants:
    """One primitive's appearance under each variant that maps it.

    ``default`` is the appearance and sidedness the primitive has with no
    variant active; ``by_name`` holds, by variant name, the appearance and
    sidedness (``solid``, the inverse of glTF's ``doubleSided``) that variant
    gives it.
    """
    default: tuple[Any, bool]
    by_name: dict[str, tuple[Any, bool]] = field(default_factory=dict)

    def dressing(self, name: Optional[str]) -> tuple[Any, bool]:
        """The appearance and sidedness for variant ``name`` (None for none)."""
        if name is None:
            return self.default
        return self.by_name.get(name, self.default)


class MaterialVariants:
    """A document's variant names, and the shapes a selection re-dresses."""

    def __init__(self, names: Sequence[str] = ()) -> None:
        self.names: tuple[str, ...] = tuple(names)
        self.active: Optional[str] = None
        #: Each shape a variant re-dresses, once however many nodes draw it.
        self._shapes: dict[Any, None] = {}

    def add(self, shape: Any) -> None:
        """Re-dress ``shape`` (whose geometry has ``materialVariants``) on selection."""
        self._shapes[shape] = None

    def select(self, variant: Union[str, int, None]) -> None:
        """Make ``variant`` the active one: a name, an index into :attr:`names`,
        or None for each primitive's own material.

        Raises KeyError for a name the document does not declare, IndexError
        for an index outside :attr:`names`, TypeError for anything else.
        """
        name = self._name(variant)
        for shape in self._shapes:
            mesh = shape.geometry
            appearance, solid = mesh.materialVariants.dressing(name)
            shape.appearance = appearance
            mesh.appearance = appearance
            mesh.solid = solid
        self.active = name

    def _name(self, variant: Union[str, int, None]) -> Optional[str]:
        if variant is None:
            return None
        if isinstance(variant, bool) or not isinstance(variant, (str, int)):
            raise TypeError("a variant is a name or an index, not %r" % (variant,))
        if isinstance(variant, int):
            if not 0 <= variant < len(self.names):
                raise IndexError("variant %d of %d" % (variant, len(self.names)))
            return self.names[variant]
        if variant not in self.names:
            raise KeyError("no variant named %r; the document declares %s"
                           % (variant, list(self.names) or 'none'))
        return variant


def variant_names(extensions: Any) -> tuple[str, ...]:
    """The variant names a document's root ``extensions`` declare, in order.

    A variant with no usable name is called by its index, so that every
    variant can still be selected.
    """
    block = extensions.get(EXTENSION) if isinstance(extensions, Mapping) else None
    declared = block.get('variants') if isinstance(block, Mapping) else None
    if not isinstance(declared, list):
        return ()
    names = []
    for index, variant in enumerate(declared):
        name = variant.get('name') if isinstance(variant, Mapping) else None
        names.append(name if isinstance(name, str) and name else 'variant %d' % index)
    return tuple(names)


def primitive_mappings(primitive: Any, variant_count: int,
                       material_count: int) -> dict[int, int]:
    """A primitive's mappings as {variant index: material index}.

    A mapping naming a variant or material the document does not have is
    reported and skipped; so is a second mapping for a variant already mapped.
    """
    extensions = getattr(primitive, 'extensions', None) or {}
    block = extensions.get(EXTENSION) if isinstance(extensions, Mapping) else None
    mappings = block.get('mappings') if isinstance(block, Mapping) else None
    found: dict[int, int] = {}
    if not isinstance(mappings, list):
        return found
    for mapping in mappings:
        material = mapping.get('material') if isinstance(mapping, Mapping) else None
        variants = mapping.get('variants') if isinstance(mapping, Mapping) else None
        if not isinstance(material, int) or not _index(material, material_count) \
                or not isinstance(variants, list):
            log.warning("glTF %s mapping %r names no material of the document's %d; "
                        "skipped", EXTENSION, mapping, material_count)
            continue
        for variant in variants:
            if not _index(variant, variant_count):
                log.warning("glTF %s mapping names variant %r of %d; skipped",
                            EXTENSION, variant, variant_count)
            elif variant in found:
                log.warning("glTF %s maps variant %d twice on one primitive; the "
                            "first mapping is kept", EXTENSION, variant)
            else:
                found[variant] = material
    return found


def _index(value: Any, count: int) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and 0 <= value < count
