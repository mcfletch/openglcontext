"""X3D's programmable shaders: ComposedShader, ProgramShader and PackagedShader

An X3D `Appearance` lists shaders in its `shaders` field, in order of
preference (ISO/IEC 19775-1, 31.2.2.3). The engine's `Appearance` draws its
shape with the first one whose `language` is GLSL (or unnamed) and whose
program links; the ones before it say `isSelected FALSE`, the one chosen
`isSelected TRUE`, and each says `isValid` once it has tried to link. While
the chosen one's sources are still loading, and where none links, the shape
is drawn with its material and texture as if it listed no shaders.

- `ComposedShader` links its `ShaderPart`s, one or more a stage;
  `ProgramShader` links its `ShaderProgram`s, a stage each, and sets the
  fields each declares on the one program.
- `PackagedShader` of GLSL is one text compiled once for each stage it tests
  the macro of (``X3D_VERTEX_SHADER``, ...; :func:`~OpenGLContext.scenegraph.x3dglsl.packaged_stages`).
  Other packaged languages are not run.
- A part's `url` is read in the background, resolved against its document
  under the document's policy; a ``data:`` URI or shader text in the url is
  read at once. Its X3D 4.1 `sourceCode` is the source where it has no url
  that reads.
- The fields a shader node declares are uniforms of the same name, set again
  whenever a field is set or routed to; a texture node in one is a sampler.
- The program also gets X3D's names for the browser's state
  (:class:`X3DShaderDraw`), and the geometry's `attrib` vertex attributes.
- A program is linked when its sources are first all to hand, and again on
  `activate` TRUE; a part whose source changes in between is compiled and
  reported, and the running program is kept (Annex I.5).

The text handling, values and layouts are in
:mod:`~OpenGLContext.scenegraph.x3dglsl`, which needs no GL.
"""
from __future__ import annotations

import contextlib
import logging
from collections.abc import Iterator, Sequence
from typing import TYPE_CHECKING, Any, Optional

import numpy as np
from OpenGL import GL
from OpenGL import error as gl_error
from OpenGL.GL import shaders as GL_shaders
from pydispatch import dispatcher
from vrml import cache, fieldtypes, protofunctions
from vrml.x3d import loadsensor
from vrml.x3d import nodes as x3d

from OpenGLContext import contextresources
from OpenGLContext.loaders import background
from OpenGLContext.passes.shaderpass import (
    GEOMETRY_STAGE_PROGRAMS, ShaderAppearanceProgram, normal_matrix,
    release_geometry_stage_hold,
)
from OpenGLContext.scenegraph import geometryarrays, texturemapping, vertexsemantics, x3dglsl
from OpenGLContext.scenegraph.shaders import bind_engine_attributes

log = logging.getLogger(__name__)

__all__ = [
    'ComposedShader', 'ProgramShader', 'PackagedShader', 'ShaderPart', 'ShaderProgram',
    'X3DShaderDraw', 'LinkedProgram', 'draw_program', 'SHADER_CHANGE_SIGNAL',
]

#: Sent with a shader node as sender when what it draws with may have changed:
#: a part's source arrived, or a link was asked for.
SHADER_CHANGE_SIGNAL = 'x3d-shader-changed'

#: The GL stage each X3D stage is compiled as.
GL_STAGES = {
    'VERTEX': GL.GL_VERTEX_SHADER,
    'TESS_CONTROL': GL.GL_TESS_CONTROL_SHADER,
    'TESS_EVALUATION': GL.GL_TESS_EVALUATION_SHADER,
    'GEOMETRY': GL.GL_GEOMETRY_SHADER,
    'FRAGMENT': GL.GL_FRAGMENT_SHADER,
}

#: What a part's sources are: all to hand, still loading, or not to be had.
READY, LOADING, FAILED = 'ready', 'loading', 'failed'


# -- reading a part's source ------------------------------------------------------

def _redraw(contexts: Sequence[Any]) -> None:
    for reference in contexts:
        found = reference()
        if found is not None:
            found.triggerRedraw(1)


def prepare_source_loading() -> None:
    """Make a background source read's imports, here on the calling thread"""
    import OpenGLContext.loaders.loader  # noqa: F401 imported for the loader thread


class SourceURLField(fieldtypes.MFString):
    """A shader source's `url`: setting it reads the source again"""

    fieldType = 'MFString'

    def fset(self, client: Any, value: Any, notify: int = 1) -> Any:
        value = super().fset(client, value, notify)
        client.reload()
        return value


class SourceLoadField(fieldtypes.SFBool):
    """X3D's `load`: whether the source is read from `url`"""

    fieldType = 'SFBool'

    def fset(self, client: Any, value: Any, notify: int = 1) -> Any:
        value = super().fset(client, value, notify)
        client.reload()
        return value


class Sourced:
    """A node whose shader text is read from its `url`, or is its `sourceCode`

    :meth:`source` answers where the text has got to. The read of a url that
    names a file or a URL runs on the loader pool, resolved against the
    node's document; the one before it is dropped when `url` or `load` is set
    again.
    """

    url = SourceURLField('url', 1, list)
    load = SourceLoadField('load', 1, True)

    def reload(self) -> None:
        """Read the text from `url` again, where `load` allows"""
        generation = self.__dict__['_generation'] = self.__dict__.get('_generation', 0) + 1
        urls = [str(entry) for entry in self.__dict__.get('url', ())]
        if not urls or not self.__dict__.get('load', True):
            self.__dict__.pop('_urlText', None)
            self.__dict__['_urlState'] = None
            return
        for entry in urls:
            try:
                text = x3dglsl.inline_source(entry)
            except ValueError as err:
                log.warning('%s: url %r is not readable: %s', self, entry[:40], err)
                continue
            if text is not None:
                self._arrived(text)
                return
        self.__dict__['_urlState'] = LOADING
        loadsensor.set_load_state(self, loadsensor.LOADING)
        from OpenGLContext import context  # noqa: PLC0415 the context module imports the passes
        background.load_in_background(
            ' '.join(urls), self.loadBackground, urls, context.Context.allContexts,
            generation, prepare=prepare_source_loading)

    def _arrived(self, text: str) -> None:
        self.__dict__['_urlText'] = text
        self.__dict__['_urlState'] = READY
        loadsensor.set_load_state(self, loadsensor.LOADED)
        dispatcher.send(signal=SHADER_CHANGE_SIGNAL, sender=self)

    def loadBackground(self, urls: Sequence[str], contexts: Sequence[Any] = (),
                       generation: Any = None) -> None:
        """Read the first of `urls` that reads; runs on the loader pool"""
        from OpenGLContext.loaders.loader import Loader  # noqa: PLC0415 imported by prepare
        root = protofunctions.root(self)
        base = getattr(root, 'baseURI', None) if root else None
        for entry in urls:
            try:
                fetched = Loader(entry, baseURL=base)
            except (OSError, ValueError) as err:
                log.info('%s: url %s did not read: %s', self, entry, err)
                continue
            _resolved, _filename, file, _headers = fetched
            with contextlib.closing(file):
                data = file.read()
            if generation != self.__dict__.get('_generation'):
                return
            self._arrived(data.decode('utf-8', 'replace') if isinstance(data, bytes) else str(data))
            _redraw(contexts)
            return
        if generation != self.__dict__.get('_generation'):
            return
        self.__dict__['_urlState'] = FAILED
        loadsensor.set_load_state(self, loadsensor.FAILED)
        log.warning('%s: none of the urls %s could be read', self, list(urls))
        dispatcher.send(signal=SHADER_CHANGE_SIGNAL, sender=self)
        _redraw(contexts)

    def source(self) -> "tuple[Optional[str], Optional[str]]":
        """(state, text): READY with the text, LOADING, FAILED, or (None, None) for none

        The url's text where it has read; the `sourceCode` where there is no
        url or none of it read.
        """
        state = self.__dict__.get('_urlState')
        if state == READY:
            return READY, self.__dict__['_urlText']
        if state == LOADING:
            return LOADING, None
        code = str(getattr(self, 'sourceCode', '') or '')
        if code.strip():
            return READY, code
        if state == FAILED:
            return FAILED, None
        return None, None


class ShaderPart(Sourced, x3d.ShaderPart):
    """One piece of a ComposedShader's program, for the stage its `type` names

    `type` is VERTEX, FRAGMENT, GEOMETRY, TESS_CONTROL or TESS_EVALUATION
    (any case); the tessellation stages need a GL 4.0 context. A part with no
    url and no `sourceCode` is passed over.
    """


class ShaderProgram(Sourced, x3d.ShaderProgram):
    """One stage of a ProgramShader, with the fields it declares as uniforms"""


# -- the program in one context ----------------------------------------------------

#: GL uniform type: (values an element, kind) -- 'f', 'i', 'u', 'm2'/'m3'/'m4'
#: or 'sampler'.
_UNIFORM_TYPES: "dict[int, tuple[int, str]]" = {
    GL.GL_FLOAT: (1, 'f'), GL.GL_FLOAT_VEC2: (2, 'f'), GL.GL_FLOAT_VEC3: (3, 'f'),
    GL.GL_FLOAT_VEC4: (4, 'f'),
    GL.GL_INT: (1, 'i'), GL.GL_INT_VEC2: (2, 'i'), GL.GL_INT_VEC3: (3, 'i'),
    GL.GL_INT_VEC4: (4, 'i'),
    GL.GL_BOOL: (1, 'i'), GL.GL_BOOL_VEC2: (2, 'i'), GL.GL_BOOL_VEC3: (3, 'i'),
    GL.GL_BOOL_VEC4: (4, 'i'),
    GL.GL_UNSIGNED_INT: (1, 'u'), GL.GL_UNSIGNED_INT_VEC2: (2, 'u'),
    GL.GL_UNSIGNED_INT_VEC3: (3, 'u'), GL.GL_UNSIGNED_INT_VEC4: (4, 'u'),
    GL.GL_FLOAT_MAT2: (4, 'm2'), GL.GL_FLOAT_MAT3: (9, 'm3'), GL.GL_FLOAT_MAT4: (16, 'm4'),
}

#: Sampler type: the texture target it reads.
_SAMPLERS = {
    GL.GL_SAMPLER_2D: GL.GL_TEXTURE_2D, GL.GL_SAMPLER_2D_SHADOW: GL.GL_TEXTURE_2D,
    GL.GL_SAMPLER_CUBE: GL.GL_TEXTURE_CUBE_MAP, GL.GL_SAMPLER_3D: GL.GL_TEXTURE_3D,
    GL.GL_SAMPLER_2D_ARRAY: GL.GL_TEXTURE_2D_ARRAY,
}

_TEXTURE_BINDINGS = {
    GL.GL_TEXTURE_2D: GL.GL_TEXTURE_BINDING_2D,
    GL.GL_TEXTURE_CUBE_MAP: GL.GL_TEXTURE_BINDING_CUBE_MAP,
    GL.GL_TEXTURE_3D: GL.GL_TEXTURE_BINDING_3D,
    GL.GL_TEXTURE_2D_ARRAY: GL.GL_TEXTURE_BINDING_2D_ARRAY,
}

_VECTOR_UPLOADS = {
    ('f', 1): GL.glUniform1fv, ('f', 2): GL.glUniform2fv, ('f', 3): GL.glUniform3fv,
    ('f', 4): GL.glUniform4fv, ('i', 1): GL.glUniform1iv, ('i', 2): GL.glUniform2iv,
    ('i', 3): GL.glUniform3iv, ('i', 4): GL.glUniform4iv, ('u', 1): GL.glUniform1uiv,
    ('u', 2): GL.glUniform2uiv, ('u', 3): GL.glUniform3uiv, ('u', 4): GL.glUniform4uiv,
}
_MATRIX_UPLOADS = {'m2': GL.glUniformMatrix2fv, 'm3': GL.glUniformMatrix3fv,
                   'm4': GL.glUniformMatrix4fv}


class LinkedProgram:
    """A linked program and what it declares: uniforms, samplers, stages

    Uploads are remembered by location, so a value the program already holds
    is not sent again.
    """

    def __init__(self, program: int, prepared: Sequence[x3dglsl.Prepared],
                 stages: Sequence[str]) -> None:
        self.program = int(program)
        #: Identifiers renamed in translated parts, by the field name.
        self.renamed: dict[str, str] = {}
        for entry in prepared:
            self.renamed.update(entry.renamed)
        #: Whether the program tessellates, so the geometry is drawn as patches.
        self.patches = 'TESS_EVALUATION' in stages
        #: name -> (GL type, size), for every active uniform; an array also
        #: under its name without ``[0]``.
        self.declared: dict[str, tuple[int, int]] = {}
        self._locations: dict[str, int] = {}
        self._uploaded: dict[int, bytes] = {}
        #: The user values last uploaded, by the node they came from.
        self.user_values: dict[int, Any] = {}
        #: sampler name -> (texture unit, target), every sampler its own unit.
        self.samplers: dict[str, tuple[int, int]] = {}
        count = int(GL.glGetProgramiv(self.program, GL.GL_ACTIVE_UNIFORMS) or 0)
        unit = 0
        GL.glUseProgram(self.program)
        for index in range(count):
            name, size, kind = GL.glGetActiveUniform(self.program, index)
            name = name.decode('ascii', 'replace') if isinstance(name, bytes) else str(name)
            self.declared[name] = (int(kind), int(size))
            if name.endswith('[0]'):
                self.declared[name[:-3]] = (int(kind), int(size))
            target = _SAMPLERS.get(int(kind))
            if target is None:
                continue
            base = name[:-3] if name.endswith('[0]') else name
            elements = [base] if int(size) == 1 and not name.endswith('[0]') else [
                '%s[%d]' % (base, element) for element in range(int(size))]
            for element in elements:
                location = self.location(element)
                if location != -1:
                    GL.glUniform1i(location, unit)
                    self.samplers[element] = (unit, target)
                    unit += 1

    def names(self) -> Iterator[int]:
        yield self.program

    def location(self, name: str) -> int:
        """The uniform's location; -1 for one the program does not use"""
        found = self._locations.get(name)
        if found is None:
            found = self._locations[name] = int(GL.glGetUniformLocation(self.program, name))
        return found

    def kind(self, name: str) -> Optional[tuple[int, int]]:
        """(GL type, size) the program declares `name` with; None for none"""
        return self.declared.get(name)

    def set(self, name: str, values: Any) -> None:
        """Upload `values` to uniform `name`, as the type the program declares"""
        location = self.location(name)
        if location == -1:
            return
        declared = self.kind(name)
        if declared is None:
            return
        gl_type, size = declared
        shape = _UNIFORM_TYPES.get(gl_type)
        if shape is None:
            return
        width, kind = shape
        array = np.asarray(values)
        if kind in ('i', 'u'):
            data = np.ascontiguousarray(array, dtype=np.int32 if kind == 'i' else np.uint32).ravel()
        else:
            data = np.ascontiguousarray(array, dtype=np.float32).ravel()
        elements = min(len(data) // width, size)
        if elements < 1:
            return
        data = data[:elements * width]
        packed = data.tobytes()
        if self._uploaded.get(location) == packed:
            return
        self._uploaded[location] = packed
        if kind.startswith('m'):
            _MATRIX_UPLOADS[kind](location, elements, GL.GL_FALSE, data)
        else:
            _VECTOR_UPLOADS[(kind, width)](location, elements, data)

    def set_field(self, name: str, found: x3dglsl.Uniform) -> None:
        """Upload a field's value to the uniform of its name, fitted to its declaration"""
        name = self.renamed.get(name, name)
        declared = self.kind(name)
        if declared is None:
            return
        shape = _UNIFORM_TYPES.get(declared[0])
        if shape is None:
            return
        width, kind = shape
        converted = x3dglsl.convert_uniform(found, width, kind in ('i', 'u'), declared[1])
        if converted is not None:
            self.set(name, converted)


def geometry_layout(geometry: Any) -> "tuple[tuple[str, int], ...]":
    """Where `geometry`'s `attrib` vertex attributes are read in this context"""
    return geometryarrays.named_layout(
        (name, locations) for name, _values, locations in x3dglsl.vertex_attributes(
            getattr(geometry, 'attrib', None)))


class ShaderState:
    """One shader node's programs in one context: one a geometry attribute layout"""

    def __init__(self) -> None:
        self.schedule = x3dglsl.LinkSchedule()
        #: The `activate` count this context has acted on.
        self.activations = 0
        #: The sources the programs are linked from, or None before a link.
        self.sources: Optional[tuple[tuple[str, str], ...]] = None
        self.programs: dict[Any, Optional[LinkedProgram]] = {}
        #: The compile or link log of the last link that failed.
        self.log = ''

    def names(self) -> Iterator[int]:
        for linked in self.programs.values():
            if linked is not None:
                yield linked.program

    def drop(self) -> None:
        """Delete the programs, which the context the state is for has current"""
        for name in list(self.names()):
            delete_program(name)
        self.programs = {}


def delete_program(name: int) -> None:
    """Delete a linked program, bound first where it has a geometry stage

    See :func:`~OpenGLContext.passes.shaderpass.release_geometry_stage_hold`.
    """
    release_geometry_stage_hold([name])
    GEOMETRY_STAGE_PROGRAMS.discard(int(name))
    GL.glDeleteProgram(name)


_STATES = contextresources.ContextNames(
    '_x3dShaderStates', delete_program, names=lambda state: list(state.names()))


def _compile(stage: str, text: str) -> int:
    kind = GL_STAGES[stage]
    try:
        shader = GL.glCreateShader(kind)
    except gl_error.GLError as err:
        raise RuntimeError('this context has no %s stage' % (stage.lower(),)) from err
    if not shader:
        raise RuntimeError('this context has no %s stage' % (stage.lower(),))
    GL.glShaderSource(shader, text)
    GL.glCompileShader(shader)
    if GL.glGetShaderiv(shader, GL.GL_COMPILE_STATUS) != GL.GL_TRUE:
        message = GL.glGetShaderInfoLog(shader)
        GL.glDeleteShader(shader)
        raise RuntimeError('%s stage: %s' % (stage.lower(), _text(message)))
    return int(shader)


def _text(message: Any) -> str:
    return message.decode('utf-8', 'replace') if isinstance(message, bytes) else str(message)


def link(sources: Sequence[tuple[str, str]], layout: Sequence[tuple[str, int]],
         max_lights: int) -> LinkedProgram:
    """A program linked from `sources`, (stage, text) each, reading `layout`'s attributes

    Each text is made ready for the compiler (:func:`x3dglsl.prepare_source`);
    the engine's and X3D's vertex input names are bound to the engine's
    locations, and each attribute of `layout` to its own. Raises
    RuntimeError with the compiler's or linker's log.
    """
    prepared = [x3dglsl.prepare_source(text, stage, max_lights) for stage, text in sources]
    shaders: list[int] = []
    program = int(GL.glCreateProgram())
    try:
        for (stage, _text_), ready in zip(sources, prepared):
            shaders.append(_compile(stage, ready.text))
        for shader in shaders:
            GL.glAttachShader(program, shader)
        bind_engine_attributes(program)
        for name, semantic in x3dglsl.X3D_INPUTS:
            GL.glBindAttribLocation(program, vertexsemantics.location(semantic), name)
        for name, location in layout:
            GL.glBindAttribLocation(program, location, name)
        for ready in prepared:
            for output in ready.outputs:
                GL.glBindFragDataLocation(program, 0, output)
        GL.glLinkProgram(program)
        if GL.glGetProgramiv(program, GL.GL_LINK_STATUS) != GL.GL_TRUE:
            raise RuntimeError('link: %s' % (_text(GL.glGetProgramInfoLog(program)),))
    except BaseException:
        GL.glDeleteProgram(program)
        raise
    finally:
        for shader in shaders:
            GL.glDeleteShader(shader)
    if any(stage == 'GEOMETRY' for stage, _source in sources):
        GEOMETRY_STAGE_PROGRAMS.add(program)
    return LinkedProgram(program, prepared, [stage for stage, _ in sources])


# -- the shader nodes ------------------------------------------------------------

def _declared_by(node: Any) -> type:
    """The X3D declaration `node`'s own fields are the fields of"""
    for cls in type(node).__mro__:
        if cls.__module__ == x3d.__name__ and getattr(cls, 'PROTO', None):
            return cls
    return type(node)


def user_fields(node: Any) -> "list[Any]":
    """The fields and events `node` declares for itself, beyond its X3D declaration's"""
    base = _declared_by(node)
    known = {entry.name for entry in protofunctions.getFields(base)}
    known.update(entry.name for entry in protofunctions.getFields(base, events=1))
    found = [entry for entry in protofunctions.getFields(node)
             if entry.name not in known and not entry.name.startswith(' ')]
    found.extend(entry for entry in protofunctions.getFields(node, events=1)
                 if entry.name not in known and not entry.direction)
    return found


#: The key a node's user values are kept under in vrml's cache.
VALUES_KEY = 'x3d-shader-values'


def field_values(node: Any) -> "tuple[list[tuple[str, x3dglsl.Uniform]], list[tuple[str, Any]]]":
    """`node`'s declared field values as uniforms, and its texture fields, by name

    A field or event with no value yet is left out; a node in an SFNode or
    MFNode field is a texture (``name[i]`` for an MFNode's).
    """
    uniforms: list[tuple[str, x3dglsl.Uniform]] = []
    textures: list[tuple[str, Any]] = []
    for declared in user_fields(node):
        try:
            value = getattr(node, declared.name)
        except AttributeError:
            continue
        type_name = str(declared.typeName())
        if type_name == 'SFNode':
            if value:
                textures.append((declared.name, value))
            continue
        if type_name == 'MFNode':
            textures.extend(('%s[%d]' % (declared.name, index), entry)
                            for index, entry in enumerate(value or ()) if entry)
            continue
        found = x3dglsl.uniform_values(type_name, value)
        if found is not None:
            uniforms.append((declared.name, found))
    return uniforms, textures


def user_values(node: Any) -> "tuple[list[tuple[str, x3dglsl.Uniform]], list[tuple[str, Any]]]":
    """:func:`field_values`, kept in vrml's cache until a declared field is set or sent an event"""
    held = cache.CACHE.getData(node, VALUES_KEY)
    if held is not None:
        return held  # type: ignore[no-any-return]  # what the holder below was given
    held = field_values(node)
    holder = cache.CACHE.holder(node, held, VALUES_KEY)
    for declared in user_fields(node):
        holder.depend(node, declared)
    return held


class X3DShader:
    """What the three X3D shader nodes share: choosing, linking and drawing

    A subclass says where its stages come from (:meth:`stageSources`) and
    which nodes' fields are its uniforms (:meth:`uniformNodes`).
    """

    if TYPE_CHECKING:
        # The X3D declaration's fields, which the class beside this one has.
        language: Any
        isSelected: Any
        isValid: Any

    def on_activate(self, value: Any, **named: Any) -> None:
        """`activate` TRUE links the program again, in every context, at its next draw"""
        if value:
            self.__dict__['_activations'] = self.__dict__.get('_activations', 0) + 1
            dispatcher.send(signal=SHADER_CHANGE_SIGNAL, sender=self)

    def runs(self) -> bool:
        """Whether the shader's language is one the engine runs"""
        return x3dglsl.speaks_glsl(getattr(self, 'language', ''))

    def stageSources(self) -> "tuple[Optional[str], tuple[tuple[str, str], ...]]":
        """(state, sources): READY with (stage, text) for each, LOADING or FAILED"""
        raise NotImplementedError

    def uniformNodes(self) -> "list[Any]":
        """The nodes whose declared fields are this shader's uniforms"""
        return [self]

    def report(self, isSelected: Optional[bool] = None, isValid: Optional[bool] = None) -> None:
        """Send `isSelected` and `isValid` where they differ from what was last sent"""
        for name, value in (('isSelected', isSelected), ('isValid', isValid)):
            if value is None:
                continue
            key = '_sent_' + name
            if self.__dict__.get(key) is value:
                continue
            self.__dict__[key] = value
            setattr(self, name, value)

    def linkedProgram(self, mode: Any, layout: Any) -> "tuple[str, Optional[LinkedProgram]]":
        """(state, program) for drawing `layout`'s attributes in the current context

        READY with the program; LOADING while a source is still being read;
        FAILED where the sources cannot be had or do not link.
        """
        entries = _STATES.entries(self)
        if entries is None:
            return FAILED, None
        state = entries.get('state')
        if state is None:
            state = entries['state'] = ShaderState()
        activations = self.__dict__.get('_activations', 0)
        if activations != state.activations:
            state.activations = activations
            state.schedule.activate()
        found, sources = self.stageSources()
        max_lights = int(getattr(getattr(mode, 'shader_program', None), 'MAX_LIGHTS', 8) or 8)
        if found == READY and state.schedule.due(sources):
            self._relink(state, sources, layout, max_lights)
        if state.sources is None:
            return (LOADING if found == LOADING else FAILED), None
        if layout not in state.programs:
            state.programs[layout] = self._link(state, state.sources, layout, max_lights)
        linked = state.programs[layout]
        return (READY, linked) if linked is not None else (FAILED, None)

    def _relink(self, state: ShaderState, sources: Any, layout: Any, max_lights: int) -> None:
        """Link `sources` in place of whatever the state was running"""
        linked = self._link(state, sources, layout, max_lights)
        state.drop()
        state.schedule.linked(sources, linked is not None)
        state.sources = sources if linked is not None else None
        if linked is not None:
            state.programs[layout] = linked

    def _link(self, state: ShaderState, sources: Any, layout: Any,
              max_lights: int) -> Optional[LinkedProgram]:
        try:
            return link(sources, layout, max_lights)
        except RuntimeError as err:
            state.log = str(err)
            log.warning('%s does not link: %s', self, err)
            return None

    def drawProgram(self, mode: Any, shape: Any) -> "tuple[str, Optional[X3DShaderDraw]]":
        """(state, draw): the program bound for `shape` and given its uniforms

        State as :meth:`linkedProgram`; the draw only where it is READY.
        """
        if not self.runs():
            return FAILED, None
        geometry = getattr(shape, 'geometry', None)
        found, linked = self.linkedProgram(mode, geometry_layout(geometry))
        if linked is None:
            return found, None
        drawn = X3DShaderDraw(linked, self, mode, shape)
        drawn.begin()
        return READY, drawn


def complete(shader: Any, found: "list[tuple[str, str]]") -> "tuple[str, tuple[tuple[str, str], ...]]":
    """READY with `found` where it has a vertex and a fragment stage; FAILED otherwise

    GL links a program with no fragment stage and leaves its colour
    undefined, so a shader is held to have both, as WebGL holds every one.
    """
    stages = {stage for stage, _text in found}
    if {'VERTEX', 'FRAGMENT'} <= stages:
        return READY, tuple(found)
    if found:
        log.warning('%s has no %s stage, and is not drawn with', shader,
                    ' or '.join(sorted({'VERTEX', 'FRAGMENT'} - stages)).lower())
    return FAILED, ()


class ComposedShader(X3DShader, x3d.ComposedShader):
    """A program linked from the `ShaderPart`s in `parts`"""

    def stageSources(self) -> "tuple[Optional[str], tuple[tuple[str, str], ...]]":
        found: list[tuple[str, str]] = []
        for part in self.parts:
            if not part:
                continue
            state, text = part.source() if hasattr(part, 'source') else (None, None)
            if state is None:
                continue
            if state != READY or text is None:
                return state, ()
            stage = x3dglsl.stage_of(getattr(part, 'type', ''))
            if stage is None:
                log.warning('%s: no %s stage', self, getattr(part, 'type', ''))
                return FAILED, ()
            found.append((stage, text))
        return complete(self, found)


class ProgramShader(X3DShader, x3d.ProgramShader):
    """A program linked from the `ShaderProgram`s in `programs`, a stage each

    The fields each `ShaderProgram` declares are uniforms of the one program.
    """

    def stageSources(self) -> "tuple[Optional[str], tuple[tuple[str, str], ...]]":
        found: list[tuple[str, str]] = []
        for program in self.programs:
            if not program:
                continue
            state, text = program.source()
            if state is None:
                continue
            if state != READY or text is None:
                return state, ()
            stage = x3dglsl.stage_of(program.type)
            if stage is None:
                log.warning('%s: no %s stage', self, program.type)
                return FAILED, ()
            found.append((stage, text))
        return complete(self, found)

    def uniformNodes(self) -> "list[Any]":
        return [program for program in self.programs if program]


class PackagedShader(Sourced, X3DShader, x3d.PackagedShader):
    """One GLSL text holding every stage, compiled once for each

    Each stage the text tests the macro of (``X3D_VERTEX_SHADER``, ...) is
    compiled with that macro defined. A `language` other than GLSL is not
    run.
    """

    def runs(self) -> bool:
        return str(getattr(self, 'language', '') or '').strip().upper() == 'GLSL'

    def stageSources(self) -> "tuple[Optional[str], tuple[tuple[str, str], ...]]":
        state, text = self.source()
        if state != READY or text is None:
            return state or FAILED, ()
        return READY, tuple((stage, text) for stage in x3dglsl.packaged_stages(text))


def draw_program(appearance: Any, mode: Any, shape: Any) -> "Optional[X3DShaderDraw]":
    """The first of `appearance`'s shaders that draws, bound for `shape`; None for none

    Each shader before it is sent `isSelected FALSE`; the one drawing
    `isSelected TRUE`; each that tried to link `isValid`. A shader still
    loading its sources stops the search, and the shape is drawn with its
    material until it has them.
    """
    for shader in appearance.shaders or ():
        if not isinstance(shader, X3DShader):
            continue
        found, drawn = shader.drawProgram(mode, shape)
        if found == READY:
            shader.report(isSelected=True, isValid=True)
            return drawn
        if found == LOADING:
            return None
        shader.report(isSelected=False, isValid=False if shader.runs() else None)
    return None


# -- what a drawn shape gives its program -----------------------------------------

def _texture_matrix(transform: Any) -> np.ndarray:
    """A texture transform as the 4x4 `x3d_TextureMatrix` applies to (s, t, r, q)"""
    flat = texturemapping.transform_matrix(transform)
    found = np.eye(4, dtype=np.float32)
    found[0, 0], found[0, 1], found[0, 3] = flat[0]
    found[1, 0], found[1, 1], found[1, 3] = flat[1]
    # Uploaded untransposed, so GL reads the rows here as columns.
    return np.ascontiguousarray(found.T)


def _textures(appearance: Any) -> "list[Any]":
    texture = getattr(appearance, 'texture', None)
    if not texture:
        return []
    inner = getattr(texture, 'texture', None)
    if isinstance(inner, list):
        return [entry for entry in inner if entry]
    return [texture]


def _transforms(appearance: Any) -> "list[Any]":
    transform = getattr(appearance, 'textureTransform', None)
    if not transform:
        return []
    inner = getattr(transform, 'textureTransform', None)
    if isinstance(inner, list):
        return list(inner)
    return [transform]


_LIGHT_MEMBERS = ('type', 'color', 'intensity', 'ambientIntensity', 'attenuation',
                  'location', 'direction', 'radius', 'beamWidth', 'cutOffAngle', 'matrix')


class X3DShaderDraw(ShaderAppearanceProgram):
    """An X3D shader's program while it draws one shape

    Stands in for the pass's programs as the geometry draws
    (:class:`~OpenGLContext.passes.shaderpass.ShaderAppearanceProgram`), and
    gives the program what X3D's binding names, where it declares them:

    - `x3d_ModelViewMatrix`, `x3d_ProjectionMatrix`,
      `x3d_ModelViewProjectionMatrix` (mat4), `x3d_NormalMatrix` (mat3),
      `x3d_ViewMatrix` and `x3d_CameraSpaceMatrix` (world to eye and back),
      `x3d_Viewport` (ivec4);
    - `x3d_Material` (an `x3d_MaterialParameters`,
      `x3d_PhysicalMaterialParameters` or `x3d_UnlitMaterialParameters`);
    - `x3d_LightSource[i]` (`x3d_LightSourceParameters`), the lights lighting
      the shape, eye space, the slots after them `x3d_NoneLight`;
    - `x3d_Texture2D[i]`, `x3d_TextureCube[i]`, `x3d_Texture3D[i]` and
      `x3d_TextureMatrix[i]` from the appearance's texture and transform;
    - the declared fields of the shader's nodes, and their textures.

    A translated GLSL 1.x program gets its built-ins' stand-ins too. The pass's
    texture bindings on the units the program's samplers use are put back
    when the shape is drawn.
    """

    def __init__(self, linked: LinkedProgram, shader: X3DShader, mode: Any, shape: Any) -> None:
        super().__init__(linked.program)
        self.linked = linked
        self.shader = shader
        self.mode = mode
        self.shape = shape
        self._restore: list[tuple[int, int, int]] = []

    # -- what the geometry asks of it
    def set_matrices(self, modelview: Any, projection: Any, program: Any = None) -> None:
        """The shape's matrices, and those made from them"""
        linked = self.linked
        mv = np.ascontiguousarray(modelview, dtype=np.float32).reshape(4, 4)
        pr = np.ascontiguousarray(projection, dtype=np.float32).reshape(4, 4)
        linked.set('x3d_ModelViewMatrix', mv)
        linked.set('x3d_ProjectionMatrix', pr)
        if linked.location('x3d_ModelViewProjectionMatrix') != -1:
            linked.set('x3d_ModelViewProjectionMatrix', mv @ pr)
        if linked.location('x3d_NormalMatrix') != -1:
            linked.set('x3d_NormalMatrix', normal_matrix(mv))

    def use(self, lit: bool = True, vertex_colors: bool = False) -> bool:
        GL.glUseProgram(self.program)
        return True

    # -- binding
    def begin(self) -> None:
        """Bind the program and give it everything it declares for this shape"""
        mode, linked = self.mode, self.linked
        GL.glUseProgram(linked.program)
        if linked.patches:
            GL.glPatchParameteri(GL.GL_PATCH_VERTICES, 3)
            mode.patchVertices = 3
        pass_program = getattr(mode, 'shader_program', None)
        linked.set(x3dglsl.OBJECT_ID_UNIFORM,
                   [int(getattr(pass_program, '_current_object_id', 0) or 0)])
        projection = getattr(mode, 'projection', None)
        if projection is None:
            projection = mode.getProjection()
        self.set_matrices(mode.matrix, projection)
        view = getattr(mode, 'shaderViewMatrix', None)
        if view is not None:
            linked.set('x3d_ViewMatrix', view)
            if linked.location('x3d_CameraSpaceMatrix') != -1:
                linked.set('x3d_CameraSpaceMatrix', np.linalg.inv(np.asarray(view, np.float64)))
        if linked.location('x3d_Viewport') != -1:
            linked.set('x3d_Viewport', [int(v) for v in mode.getViewport()])
        appearance = getattr(self.shape, 'appearance', None)
        self._material(getattr(appearance, 'material', None))
        self._lights(pass_program)
        self._userValues()
        self._bindTextures(appearance)

    def end(self) -> None:
        """Put back the texture bindings the shape's samplers replaced"""
        for unit, target, previous in reversed(self._restore):
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            GL.glBindTexture(target, previous)
        if self._restore:
            GL.glActiveTexture(GL.GL_TEXTURE0)
        self._restore = []
        if self.linked.patches:
            self.mode.patchVertices = 0

    def _material(self, material: Any) -> None:
        linked = self.linked
        values = x3dglsl.material_parameters(material)
        for structure in ('x3d_Material', 'x3d_FrontMaterial'):
            for name, value in values.items():
                linked.set('%s.%s' % (structure, name), value)
        if linked.location('oglc_FrontMaterial.diffuse') == -1 and linked.location(
                'oglc_FrontMaterial.emission') == -1 and linked.location(
                'oglc_FrontLightProduct[0].diffuse') == -1 and linked.location(
                'oglc_FrontLightModelProduct.sceneColor') == -1:
            self._legacyMaterial = None
            return
        legacy = x3dglsl.legacy_material_parameters(values)
        self._legacyMaterial = legacy
        for name, value in legacy.items():
            linked.set('oglc_FrontMaterial.%s' % name, value)
        ambient = np.array((0.2, 0.2, 0.2, 1.0), np.float32)
        linked.set('oglc_LightModel.ambient', ambient)
        linked.set('oglc_FrontLightModelProduct.sceneColor',
                   legacy['emission'] + legacy['ambient'] * ambient)

    _legacyMaterial: Optional[dict[str, Any]] = None

    def _lights(self, pass_program: Any) -> None:
        linked, mode = self.linked, self.mode
        slots = int(getattr(pass_program, 'MAX_LIGHTS', 8) or 8)
        if (linked.location('x3d_LightSource[0].type') == -1
                and linked.location('oglc_LightSource[0].position') == -1
                and linked.location('oglc_FrontLightProduct[0].diffuse') == -1):
            return
        found: list[Optional[dict[str, Any]]] = [
            x3dglsl.light_parameters(light, matrix)
            for light, matrix in getattr(mode, 'shaderLights', ())]
        if getattr(mode, 'shaderHeadlight', False):
            found.append(x3dglsl.headlight_parameters())
        off = int(getattr(pass_program, '_lights_off', 0) or 0)
        for slot in range(slots):
            light = found[slot] if slot < len(found) and not off & (1 << slot) else None
            if light is None:
                linked.set('x3d_LightSource[%d].type' % slot, [0])
                for member in ('ambient', 'diffuse', 'specular'):
                    linked.set('oglc_LightSource[%d].%s' % (slot, member), np.zeros(4, np.float32))
                    linked.set('oglc_FrontLightProduct[%d].%s' % (slot, member),
                               np.zeros(4, np.float32))
                continue
            for member in _LIGHT_MEMBERS:
                value = light[member]
                linked.set('x3d_LightSource[%d].%s' % (slot, member),
                           [value] if np.ndim(value) == 0 else value)
            legacy = x3dglsl.legacy_light_parameters(light)
            for member, value in legacy.items():
                linked.set('oglc_LightSource[%d].%s' % (slot, member),
                           [value] if np.ndim(value) == 0 else value)
            material = self._legacyMaterial
            if material is not None:
                for member in ('ambient', 'diffuse', 'specular'):
                    linked.set('oglc_FrontLightProduct[%d].%s' % (slot, member),
                               material[member] * legacy[member])

    def _userValues(self) -> None:
        linked = self.linked
        for owner in self.shader.uniformNodes():
            uniforms, _textures_ = user_values(owner)
            key = id(owner)
            if linked.user_values.get(key) is uniforms:
                continue
            linked.user_values[key] = uniforms
            for name, found in uniforms:
                linked.set_field(name, found)

    def _bindTextures(self, appearance: Any) -> None:
        linked, mode = self.linked, self.mode
        if not linked.samplers:
            return
        wanted: dict[str, Any] = {}
        counts = {GL.GL_TEXTURE_2D: 0, GL.GL_TEXTURE_CUBE_MAP: 0, GL.GL_TEXTURE_3D: 0}
        names = {GL.GL_TEXTURE_2D: 'x3d_Texture2D', GL.GL_TEXTURE_CUBE_MAP: 'x3d_TextureCube',
                 GL.GL_TEXTURE_3D: 'x3d_Texture3D'}
        for texture in _textures(appearance):
            held = texture.cached(mode) if hasattr(texture, 'cached') else None
            target = int(getattr(held, 'target', GL.GL_TEXTURE_2D) or GL.GL_TEXTURE_2D)
            if target not in counts:
                continue
            wanted['%s[%d]' % (names[target], counts[target])] = held
            counts[target] += 1
        transforms = _transforms(appearance)
        for index in range(x3dglsl.MAX_TEXTURES):
            name = 'x3d_TextureMatrix[%d]' % index
            if linked.location(name) != -1:
                transform = transforms[index] if index < len(transforms) else (
                    transforms[-1] if transforms else None)
                linked.set(name, _texture_matrix(transform))
        for owner in self.shader.uniformNodes():
            for name, texture in user_values(owner)[1]:
                wanted[linked.renamed.get(name, name)] = (
                    texture.cached(mode) if hasattr(texture, 'cached') else None)
        for name, (unit, target) in linked.samplers.items():
            held = wanted.get(name)
            texture = int(getattr(held, 'texture', 0) or 0) if held is not None else 0
            GL.glActiveTexture(GL.GL_TEXTURE0 + unit)
            previous = int(GL.glGetIntegerv(_TEXTURE_BINDINGS[target]))
            self._restore.append((unit, target, previous))
            GL.glBindTexture(target, texture)
        GL.glActiveTexture(GL.GL_TEXTURE0)


def appearance_shaders(appearance: Any) -> bool:
    """Whether `appearance` lists any X3D shader"""
    return any(isinstance(shader, X3DShader) for shader in getattr(appearance, 'shaders', None) or ())

