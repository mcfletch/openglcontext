"""MTL materials as ``PhysicalMaterial`` appearances, and the files they name.

:func:`load_libraries` reads the libraries an OBJ names, and
:class:`MaterialBuilder` turns each :class:`~OpenGLContext.loaders.mtlfile.MtlMaterial`
into an ``Appearance`` holding a ``PhysicalMaterial``:

- ``Kd`` is the base colour, white where a ``map_Kd`` replaces it.
- ``Pr`` is the roughness. Without it, ``Ns`` gives ``1 - sqrt(Ns / 1000)``,
  which is how Blender reads an MTL, and a material that states neither is half
  rough. ``Pm`` is the metalness, 0 where absent.
- ``Ks`` sets the strength of the specular highlight: twice its mean, to a
  limit of 1, since a ``Ks`` of 0.5 is the usual default and is the engine's
  full dielectric highlight. ``illum 0`` and ``illum 1`` have none.
- ``d`` and ``Tr`` give the base colour's alpha. A ``map_d`` is merged into the
  alpha of the diffuse map; a mask that is clear or opaque and nothing between
  is a cutout, drawn masked, and any other blends. A material with no opacity
  map that is wholly transparent (``d 0`` or ``Tr 1``) is drawn opaque and
  logged, since a surface that draws nothing is not what a file means.
- ``map_Pr``, ``map_Pm`` and ``map_Ns`` (read as gloss) are packed into one
  metallic-roughness texture. ``norm`` is a normal map. A ``map_Bump`` or
  ``bump`` is a normal map where the picture is violet, and a height map
  converted to a normal map where it is not; ``-bm`` is the strength of either.
- ``Ke`` and ``map_Ke`` are the emission, ``Pc`` and ``Pcr`` (and their maps)
  the clearcoat, ``Ps`` the sheen, ``aniso`` and ``anisor`` the anisotropy,
  ``Ni`` the index of refraction (an index of 1 is read as unstated).
- ``-s`` and ``-o`` become a texture transform on the ``Appearance``; ``-clamp
  on`` stops a texture repeating.

``Ka``, ``map_Ka``, ``refl``, ``disp`` and ``decal`` are not used: the surface
is lit by the scene's lights and its environment.

A texture or library is looked for beside its library, then beside the model, by
the name written, by that name with ``\\`` read as ``/``, with each part's case
matched against the directory, and by its file name alone where the name is a
path from another machine. Nothing outside the model's directory is read.
"""
from __future__ import annotations

import logging
import math
import os
import posixpath
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np
from PIL import Image, ImageOps
from vrml.x3d import nodes as x3d

from OpenGLContext.loaders import objimages
from OpenGLContext.loaders.gltf.materials import khr_transform_matrix
from OpenGLContext.loaders.loader import Loader, join_reference, local_path
from OpenGLContext.loaders.mtlfile import MtlMaterial, TextureMap, parse_mtl
from OpenGLContext.loaders.resolver import check_pixels, is_url
from OpenGLContext.scenegraph.appearance import Appearance
from OpenGLContext.scenegraph.imagedata import ImageDataTexture
from OpenGLContext.scenegraph.imagetexture import ImageTexture
from OpenGLContext.scenegraph.physicalmaterial import CHANNEL_FIELDS, PhysicalMaterial

__all__ = ['LibraryMaterial', 'MaterialBuilder', 'load_libraries']

log = logging.getLogger(__name__)

#: The base colour of a surface the file gives none.
GREY = (0.8, 0.8, 0.8)
#: Roughness of a surface that states neither ``Pr`` nor ``Ns``.
DEFAULT_ROUGHNESS = 0.5


@dataclass
class LibraryMaterial:
    """A material and the directory of its library, relative to the model"""
    material: MtlMaterial
    directory: str = ''


class Locator:
    """Finds the files a document names, beside the document

    Every reference goes through the loader's resolver, so none leaves the
    directory the model was read from (or, for a served model, its origin).
    """

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url

    def candidates(self, reference: str, directory: str) -> list[str]:
        """The references to try, in order, for ``reference`` written in a library in ``directory``"""
        written = reference.replace('\\', '/')
        names = [written]
        bare = posixpath.basename(written)
        if bare and bare != written:
            names.append(bare)
        found: list[str] = []
        for name in names:
            for candidate in ((posixpath.join(directory, name),) if directory else ()) + (name,):
                if candidate not in found:
                    found.append(candidate)
        return found

    def locate(self, reference: str, directory: str = '') -> Optional[str]:
        """A reference, relative to the model, that names a file that exists; None where none does

        A model served over http is not probed: its first candidate is returned.
        """
        for candidate in self.candidates(reference, directory):
            if is_url(self.base_url):
                return candidate
            for spelled in (candidate, self.matched_case(candidate)):
                if spelled and self.exists(spelled):
                    return spelled
        return None

    def exists(self, reference: str) -> bool:
        try:
            return os.path.isfile(Loader.resolve(reference, self.base_url))
        except (IOError, ValueError):
            return False

    def matched_case(self, reference: str) -> Optional[str]:
        """``reference`` spelled as the directories hold its parts, or None where one is missing"""
        directory = os.path.dirname(local_path(self.base_url))
        spelled: list[str] = []
        for part in posixpath.normpath(reference).split('/'):
            if part in ('', '.'):
                continue
            if part == '..':
                return None
            try:
                names = os.listdir(os.path.join(directory, *spelled) if spelled else (directory or '.'))
            except OSError:
                return None
            matches = [name for name in names if name.lower() == part.lower()]
            if not matches:
                return None
            spelled.append(sorted(matches)[0])
        return '/'.join(spelled)

    def read(self, reference: str) -> bytes:
        """The bytes of ``reference``, held to the resolver's size limit"""
        data: bytes = Loader.get_reference(reference, self.base_url)[1].read()
        return data

    def url(self, reference: str) -> str:
        """``reference`` as the path or URL a texture node loads"""
        return join_reference(self.base_url, reference)


def load_libraries(libraries: list[str], base_url: str) -> dict[str, LibraryMaterial]:
    """The materials of every ``mtllib`` line of a model read from ``base_url``

    A line may name one library, whose name may hold spaces, or several
    separated by spaces. A library that cannot be found or read is logged and
    skipped, since the model still draws with its default material. A library
    that is found and is malformed raises ``ValueError`` naming it. Where two
    libraries define a name, the later one wins.
    """
    locator = Locator(base_url)
    materials: dict[str, LibraryMaterial] = {}
    for line in libraries:
        names = [line] if locator.locate(line) else line.split()
        for name in names:
            found = locator.locate(name)
            if found is None:
                log.warning('material library %r of %s was not found', name, base_url)
                continue
            try:
                data = locator.read(found)
            except (IOError, ValueError) as err:
                log.warning('material library %r of %s cannot be read: %s', name, base_url, err)
                continue
            for material in parse_mtl(data, found).values():
                materials[material.name] = LibraryMaterial(material, posixpath.dirname(found))
    return materials


def _flipped(image: Image.Image) -> Image.Image:
    """``image`` with its last row first, for a texture whose t runs up the picture"""
    return ImageOps.flip(image)


class MaterialBuilder:
    """Builds the appearances of one model's materials

    Holds what the materials of a model share: the texture node of each file,
    the decoded pictures, and the default appearance.
    """

    def __init__(self, base_url: str) -> None:
        self.locator = Locator(base_url)
        self._textures: dict[tuple[str, bool], ImageTexture] = {}
        self._pictures: dict[str, Optional[Image.Image]] = {}
        self._defaults: dict[bool, Appearance] = {}
        #: Map channels some material named and this builder does not use.
        self.unused: set[str] = set()

    def default(self, coloured: bool = False) -> Appearance:
        """The appearance of faces with no usable material: light grey, or white under vertex colours"""
        found = self._defaults.get(coloured)
        if found is None:
            found = self._defaults[coloured] = Appearance(material=PhysicalMaterial(
                baseColor=(1.0, 1.0, 1.0) if coloured else GREY, metallic=0.0, roughness=0.6))
        return found

    def appearance(self, entry: LibraryMaterial) -> Appearance:
        """The ``Appearance`` of one material"""
        return _Surface(self, entry).build()


    def locate(self, texture: TextureMap, entry: LibraryMaterial, channel: str) -> Optional[str]:
        found = self.locator.locate(texture.file, entry.directory)
        if found is None:
            log.warning('%s map %r of material %r was not found', channel, texture.file,
                        entry.material.name)
        return found

    def node(self, reference: str, clamp: bool) -> ImageTexture:
        """The shared texture node that loads ``reference``"""
        url = self.locator.url(reference)
        node = self._textures.get((url, clamp))
        if node is None:
            node = self._textures[(url, clamp)] = ImageTexture(
                url=[url], repeatS=not clamp, repeatT=not clamp)
        return node

    def picture(self, reference: str) -> Optional[Image.Image]:
        """The decoded picture at ``reference``, or None where it cannot be read"""
        if reference not in self._pictures:
            self._pictures[reference] = self._decode(reference)
        return self._pictures[reference]

    def _decode(self, reference: str) -> Optional[Image.Image]:
        import io  # noqa: PLC0415 only a map that needs its pixels
        try:
            image = Image.open(io.BytesIO(self.locator.read(reference)))
            check_pixels(image.width, image.height, what=reference)
            image.load()
        except (IOError, ValueError, SyntaxError, Image.DecompressionBombError) as err:
            log.warning('map %r cannot be read: %s', reference, err)
            return None
        return image


class _Surface:
    """One material's fields, textures and texture transforms, gathered then built"""

    def __init__(self, builder: MaterialBuilder, entry: LibraryMaterial) -> None:
        self.builder = builder
        self.entry = entry
        self.material = entry.material
        self.fields: dict[str, Any] = {}
        self.transforms: dict[tuple[float, float, float, float], Any] = {}
        self.alpha_mode = 'OPAQUE'

    def build(self) -> Appearance:
        self.base()
        self.metallic_roughness()
        self.normal()
        self.emission()
        self.specular()
        self.clearcoat()
        material = self.material
        self.fields['transparency'] = 0.0
        if material.opacity is not None and material.opacity < 1.0:
            if material.opacity <= 0.0 and 'opacity' not in material.maps:
                log.warning('material %r is wholly transparent (d 0 or Tr 1) and has no opacity '
                            'map; it is drawn opaque', material.name)
            else:
                self.fields['transparency'] = float(1.0 - material.opacity)
                if self.alpha_mode == 'OPAQUE':
                    self.alpha_mode = 'BLEND'
        for channel in ('ambient', 'reflection', 'displacement', 'decal'):
            if channel in material.maps:
                self.builder.unused.add(channel)
        appearance = Appearance(material=PhysicalMaterial(**self.fields), alphaMode=self.alpha_mode,
                                alphaCutoff=0.5)
        if self.transforms:
            appearance.textureTransform = x3d.MultiTextureTransform(
                textureTransform=list(self.transforms.values()))
        return appearance


    def mapped(self, channel: str) -> Optional[tuple[TextureMap, str]]:
        """The map of ``channel`` and where its file is, or None where there is none to read"""
        texture = self.material.maps.get(channel)
        if texture is None:
            return None
        found = self.builder.locate(texture, self.entry, channel)
        return (texture, found) if found is not None else None

    def attach(self, channel: str, node: Any, texture: TextureMap) -> None:
        """Set a material channel's texture and the mapping that applies its transform"""
        self.fields[CHANNEL_FIELDS[channel]] = node
        label = self.label(texture)
        if label:
            self.fields[CHANNEL_FIELDS[channel] + 'Mapping'] = label

    def label(self, texture: TextureMap) -> str:
        """The mapping label of ``texture``'s scale and offset: empty for none, shared by equal ones"""
        key = (texture.scale[0], texture.scale[1], texture.offset[0], texture.offset[1])
        if key == (1.0, 1.0, 0.0, 0.0):
            return ''
        if key not in self.transforms:
            label = 'TEXCOORD_0:%d' % len(self.transforms)
            self.transforms[key] = x3d.TextureTransformMatrix3D(
                mapping=label, matrix=khr_transform_matrix(
                    offset=(key[2], key[3]), rotation=0.0, scale=(key[0], key[1])))
        return str(self.transforms[key].mapping)

    def image_node(self, image: Image.Image, texture: TextureMap) -> ImageDataTexture:
        return ImageDataTexture(image=_flipped(image), repeatS=not texture.clamp,
                                repeatT=not texture.clamp)


    def base(self) -> None:
        material = self.material
        colour = material.diffuse or GREY
        diffuse = self.mapped('diffuse')
        opacity = self.mapped('opacity')
        node: Any = None
        texture: Optional[TextureMap] = None
        if diffuse is not None:
            texture = diffuse[0]
            node = self.builder.node(diffuse[1], texture.clamp)
        if opacity is not None:
            node, texture = self.with_opacity(diffuse, opacity, node, texture)
        if node is not None and texture is not None:
            self.attach('baseColor', node, texture)
            colour = (1.0, 1.0, 1.0)
        self.fields['baseColor'] = tuple(float(value) for value in colour)

    def with_opacity(self, diffuse: Optional[tuple[TextureMap, str]], opacity: tuple[TextureMap, str],
                     node: Any, texture: Optional[TextureMap]) -> tuple[Any, Optional[TextureMap]]:
        """The base texture with the opacity map merged into its alpha

        Sets the alpha mode from the mask. A diffuse map that is also the
        opacity map is used as it is, its own alpha being the mask.
        """
        mask_map, mask_file = opacity
        picture = self.builder.picture(mask_file)
        if picture is None:
            return node, texture
        channel = mask_map.channel
        if not channel and 'A' in picture.getbands():
            channel = 'm'
        mask = objimages.channel_values(
            picture, TextureMap(mask_map.file, channel=channel, base=mask_map.base, gain=mask_map.gain))
        mode = objimages.alpha_mode(mask)
        if mode == 'OPAQUE':
            return node, texture
        self.alpha_mode = mode
        if diffuse is not None and diffuse[1] == mask_file and not mask_map.channel:
            return node, texture
        colour = self.builder.picture(diffuse[1]) if diffuse is not None else None
        if diffuse is not None and colour is None:
            return node, texture
        merged = objimages.with_alpha(colour, mask)
        used = diffuse[0] if diffuse is not None else mask_map
        return self.image_node(merged, used), used

    def metallic_roughness(self) -> None:
        material = self.material
        rough_map = self.mapped('roughness')
        metal_map = self.mapped('metallic')
        gloss_map = self.mapped('shininess') if rough_map is None else None
        if material.roughness is not None:
            roughness = material.roughness
        elif rough_map is not None or gloss_map is not None:
            roughness = 1.0
        elif material.shininess is not None:
            roughness = 1.0 - math.sqrt(min(max(material.shininess, 0.0), 1000.0) / 1000.0)
        else:
            roughness = DEFAULT_ROUGHNESS
        metallic = material.metallic if material.metallic is not None else (
            1.0 if metal_map is not None else 0.0)
        values: dict[str, Optional[np.ndarray]] = {'roughness': None, 'metallic': None}
        used: Optional[TextureMap] = None
        for key, found, convert in (('roughness', rough_map, None),
                                    ('roughness', gloss_map, lambda gloss: 1.0 - np.sqrt(gloss)),
                                    ('metallic', metal_map, None)):
            if found is None:
                continue
            picture = self.builder.picture(found[1])
            if picture is None:
                continue
            scalars = objimages.channel_values(picture, found[0])
            values[key] = convert(scalars) if convert is not None else scalars
            used = used or found[0]
        if used is not None:
            image = objimages.combine_metallic_roughness(values['roughness'], values['metallic'])
            self.attach('metallicRoughness', self.image_node(image, used), used)
        elif rough_map is not None or gloss_map is not None or metal_map is not None:
            # Every map was unreadable: the factors were chosen for a map to scale.
            roughness = material.roughness if material.roughness is not None else (
                DEFAULT_ROUGHNESS if material.shininess is None else
                1.0 - math.sqrt(min(max(material.shininess, 0.0), 1000.0) / 1000.0))
            metallic = material.metallic if material.metallic is not None else 0.0
        self.fields['roughness'] = float(roughness)
        self.fields['metallic'] = float(metallic)

    def normal(self) -> None:
        for channel in ('normal', 'bump'):
            found = self.mapped(channel)
            if found is None:
                continue
            texture, reference = found
            self.fields['normalScale'] = float(texture.bump_multiplier)
            picture = self.builder.picture(reference) if channel == 'bump' else None
            if channel == 'bump' and picture is None:
                self.fields.pop('normalScale')
                continue
            if picture is not None and not objimages.looks_like_normal_map(picture):
                height = objimages.channel_values(picture, TextureMap(texture.file))
                converted = objimages.normal_from_height(height, texture.bump_multiplier)
                self.fields['normalScale'] = 1.0
                self.attach('normal', self.image_node(converted, texture), texture)
            else:
                self.attach('normal', self.builder.node(reference, texture.clamp), texture)
            return

    def emission(self) -> None:
        material = self.material
        colour = material.emissive or (0.0, 0.0, 0.0)
        found = self.mapped('emissive')
        if found is not None:
            self.attach('emissive', self.builder.node(found[1], found[0].clamp), found[0])
            colour = (1.0, 1.0, 1.0)
        self.fields['emissiveColor'] = tuple(float(value) for value in colour)

    def specular(self) -> None:
        material = self.material
        if material.illum in (0, 1):
            self.fields['specular'] = 0.0
        elif material.specular is not None:
            self.fields['specular'] = float(min(1.0, 2.0 * sum(material.specular) / 3.0))
        if material.ior is not None and material.ior > 1.0:
            self.fields['ior'] = float(material.ior)
        if material.sheen:
            self.fields['sheenColor'] = (float(material.sheen),) * 3
        if material.anisotropy:
            self.fields['anisotropyStrength'] = float(material.anisotropy)
            self.fields['anisotropyRotation'] = float((material.anisotropy_rotation or 0.0) * 2.0 * math.pi)

    def clearcoat(self) -> None:
        material = self.material
        if material.clearcoat is not None:
            self.fields['clearcoat'] = float(material.clearcoat)
        if material.clearcoat_roughness is not None:
            self.fields['clearcoatRoughness'] = float(material.clearcoat_roughness)
        for channel, field in (('clearcoat', 'clearcoat'), ('clearcoat_roughness', 'clearcoatRoughness')):
            found = self.mapped(channel)
            if found is not None:
                self.attach(field, self.builder.node(found[1], found[0].clamp), found[0])
                self.fields.setdefault(field, 1.0)
