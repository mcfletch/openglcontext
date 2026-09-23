"""Say what a material or an object *is*, and export it as a glTF extension.

A panel on the material tab and one on the object tab, each naming a ``kind``
and its parameters, and an exporter extension that writes them into the glTF as
``OGLC_hook``. OpenGLContext reads that tag at load and makes something of it --
a tagged surface loads as moving water rather than as a flat blue sheet.

The same tag can be written without this add-on, as a custom property called
``OGLC_hook`` on the material, exported with Include > Custom Properties ticked.
This is for pipelines that would rather have the extension: it needs nothing
ticked, it is a form rather than a JSON string, and what it writes is checked as
it is typed.

The rules live in :mod:`tag`, which imports no Blender and is where they are
tested. This half is the properties, the panels and the two exporter hooks.
"""
import importlib
import logging

import bpy
from bpy.props import (
    BoolProperty, EnumProperty, FloatProperty, PointerProperty, StringProperty,
)
from bpy.types import Panel, PropertyGroup

from . import tag

bl_info = {
    'name': 'glTF engine hooks (OpenGLContext)',
    'author': 'Mike C. Fletcher',
    'version': (1, 0, 0),
    'blender': (4, 0, 0),
    'location': 'Properties > Material > Engine Hook, Properties > Object > Engine Hook',
    'description': 'Tag a material or an object with what it is, for a glTF loader to act on',
    'doc_url': 'http://pyopengl.sourceforge.net/context/gltf.html#hooks',
    'category': 'Import-Export',
}

log = logging.getLogger(__name__)

#: Where the settings hang off a material and off an object alike.
PROPERTY = 'oglc_hook'


def _items(vocabulary):
    """A Blender enum from one of :mod:`tag`'s vocabularies."""
    return [(name, name.title(), description)
            for name, description in vocabulary.items()]


class OGLCHookSettings(PropertyGroup):
    """What one material or one object is, as the panel holds it."""

    enabled: BoolProperty(
        name='Engine Hook',
        description='Write an OGLC_hook block for this material or object',
        default=False,
    )
    kind: StringProperty(
        name='Kind',
        description='What the engine should make of this. The engine ships '
                    '"water"; a game names its own, like "glisteel:rail"',
        default=tag.WATER,
    )
    style: EnumProperty(
        name='Style',
        description='How the water moves',
        items=_items(tag.STYLES),
        default=tag.DEFAULTS['style'],
    )
    material: EnumProperty(
        name='Shading',
        description='What shades the surface',
        items=_items(tag.SHADING),
        default=tag.DEFAULTS['material'],
    )
    medium: EnumProperty(
        name='Medium',
        description='What being inside the body is like',
        items=_items(tag.MEDIA),
        default=tag.DEFAULTS['medium'],
    )
    depth: FloatProperty(
        name='Depth',
        description='How far below the surface the body reaches. A surface has '
                    'no thickness, so a sheet with no depth bounds a box '
                    'nothing can be inside of',
        default=0.0, min=0.0, unit='LENGTH',
    )
    parameters: StringProperty(
        name='Parameters',
        description='A JSON object of parameters, merged over the fields '
                    'above: {"level": 12.5}',
        default='',
    )


def _draw(layout, settings):
    """The panel, and what it says the file will carry."""
    layout.use_property_split = True
    layout.prop(settings, 'enabled')
    body = layout.column()
    body.enabled = settings.enabled
    body.prop(settings, 'kind')
    if settings.kind.strip().lower() == tag.WATER:
        body.prop(settings, 'style')
        body.prop(settings, 'material')
        body.prop(settings, 'medium')
        body.prop(settings, 'depth')
    body.prop(settings, 'parameters')
    try:
        block = tag.hook_block(settings)
    except ValueError as error:
        row = body.row()
        row.alert = True
        row.label(text=str(error), icon='ERROR')
        return
    if block is not None:
        body.label(text=tag.preview(block))


class OGLC_PT_material_hook(Panel):
    bl_label = 'Engine Hook'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'material'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.material is not None

    def draw(self, context):
        _draw(self.layout, getattr(context.material, PROPERTY))


class OGLC_PT_object_hook(Panel):
    bl_label = 'Engine Hook'
    bl_space_type = 'PROPERTIES'
    bl_region_type = 'WINDOW'
    bl_context = 'object'
    bl_options = {'DEFAULT_CLOSED'}

    @classmethod
    def poll(cls, context):
        return context.object is not None

    def draw(self, context):
        _draw(self.layout, getattr(context.object, PROPERTY))


def _extension_class():
    """The exporter's own ``Extension`` wrapper, which is what lists a block in
    ``extensionsUsed``. Its module is spelled two ways across the exporter
    versions this add-on runs under."""
    for module in ('io_scene_gltf2.io.com.gltf2_io_extensions',
                   'io_scene_gltf2.io.com.extensions'):
        try:
            return importlib.import_module(module).Extension
        except (ImportError, AttributeError):
            continue
    return None


def _wrap(block):
    extension = _extension_class()
    if extension is None:
        log.warning('This glTF exporter offers no Extension class, so %s is '
                    'written without being listed in extensionsUsed',
                    tag.EXTENSION)
        return block
    return extension(name=tag.EXTENSION, extension=block, required=False)


def _apply(gltf2_object, datablock):
    """Put the block the panel describes on the material or node being written.

    A parameters field that is not JSON is logged and the export carries on
    untagged: an export that raised here would lose a session's work over a
    mistyped brace, and the panel has already said so in red.
    """
    settings = getattr(datablock, PROPERTY, None)
    if settings is None or gltf2_object is None:
        return
    try:
        block = tag.hook_block(settings)
    except ValueError as error:
        log.error('%s on %r is not written: %s', tag.EXTENSION,
                  getattr(datablock, 'name', datablock), error)
        return
    if block is None:
        return
    if gltf2_object.extensions is None:
        gltf2_object.extensions = {}
    gltf2_object.extensions[tag.EXTENSION] = _wrap(block)


class glTF2ExportUserExtension:
    """What the glTF exporter calls as it writes each material and each node."""

    def gather_material_hook(self, gltf2_material, blender_material, export_settings):
        _apply(gltf2_material, blender_material)

    def gather_node_hook(self, gltf2_node, blender_object, export_settings):
        _apply(gltf2_node, blender_object)


CLASSES = (OGLCHookSettings, OGLC_PT_material_hook, OGLC_PT_object_hook)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    for holder in (bpy.types.Material, bpy.types.Object):
        setattr(holder, PROPERTY, PointerProperty(type=OGLCHookSettings))


def unregister():
    for holder in (bpy.types.Material, bpy.types.Object):
        if hasattr(holder, PROPERTY):
            delattr(holder, PROPERTY)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
