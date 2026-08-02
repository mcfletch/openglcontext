"""What a viewer can offer to open.

``oglc-view`` with nothing named should not answer with a usage message.  It
should answer with a **shelf**: models and worlds with pictures, grouped, that
someone can look through and open.  This is that shelf.

It is *derived*, not authored a second time.  The scenes are the ones
:mod:`OpenGLContext.loaders.gltf_demos` already records -- with the framing,
backdrop and environment each of them needs -- so the library and the capture
harness cannot drift on how a model should be shown.  An application adds its
own entries with :meth:`Library.extend`.

    from OpenGLContext.viewer.library import default_library

    for entry in default_library().inCategory('Models'):
        print(entry.name, entry.source)

**Nothing here touches the network**, at import or at construction.  Preview
pictures are the exception a caller opts into: :meth:`Library.withPreviews`
fetches the Khronos catalogue (once, cached on disk) to find each sample's
reference screenshot, and being offline costs pictures and nothing else.
"""
from dataclasses import dataclass, field, replace
from functools import lru_cache
from typing import Any, Dict, Iterable, Mapping, Optional, Tuple

__all__ = ['Entry', 'Library', 'default_library', 'sample_entries',
           'world_entries', 'screenshot_urls',
           'MODELS', 'MATERIALS', 'SCENES', 'WORLDS', 'LOCAL', 'FEATURE_TESTS']

#: The shelves.  Each is a fact about the entry rather than an opinion about it:
#: what kind of source it is, and what the roster already records about how it
#: has to be shown.
MODELS = 'Models'           #: One object, framed and turned to be looked at.
MATERIALS = 'Materials'     #: Metals and glass, which need an environment.
SCENES = 'Scenes'           #: Authored cameras or an interior: places, not objects.
WORLDS = 'Worlds'           #: Complete worlds in their own coordinates.
LOCAL = 'Local builds'      #: Built beside this checkout rather than published.
#: Conformance fixtures: one glTF feature each, and not much to look at.  Most
#: of the Khronos sample set is these, and a shelf full of them is a shelf
#: nobody finds anything in.
FEATURE_TESTS = 'Feature tests'

#: The order the shelves are shown in: most to least likely to be wanted, with
#: the fixtures last, because the point of the ordering is that the first thing
#: somebody sees is worth seeing.
CATEGORY_ORDER = (MODELS, MATERIALS, SCENES, WORLDS, LOCAL, FEATURE_TESTS)


@dataclass(frozen=True)
class Entry:
    """One thing that can be opened, and what is known about showing it."""

    #: What a person calls it.
    name: str
    #: What the viewer is handed: a path, an http(s) URL, or a Khronos sample
    #: name, which the glTF loader downloads and caches.
    source: str = ''
    #: Which shelf it is on.
    category: str = MODELS
    #: A picture of it: a path or an http(s) URL.  Empty draws a plate.
    preview: str = ''
    #: One line saying what it is or what it demonstrates.
    note: str = ''
    #: :class:`~OpenGLContext.viewer.options.ViewerOptions` fields this entry
    #: wants -- the yaw it faces at, the backdrop its materials need, whether it
    #: is meant to be walked.
    options: Mapping[str, Any] = field(default_factory=dict)


class Library(object):
    """A shelf of :class:`Entry`, grouped into categories."""

    def __init__(self, entries: Iterable[Entry] = ()) -> None:
        self.entries: Tuple[Entry, ...] = tuple(entries)

    def categories(self) -> Tuple[str, ...]:
        """The categories present, in :data:`CATEGORY_ORDER` and then by name.

        A stable order, because a shelf that rearranges itself between runs is
        a shelf nobody learns their way around.
        """
        present = {entry.category for entry in self.entries}
        known = [name for name in CATEGORY_ORDER if name in present]
        return tuple(known + sorted(present - set(CATEGORY_ORDER)))

    def inCategory(self, category: str) -> Tuple[Entry, ...]:
        """Everything on one shelf, in the order it was added."""
        return tuple(entry for entry in self.entries
                     if entry.category == category)

    def find(self, name: str) -> Optional[Entry]:
        """The entry called ``name``, or None."""
        for entry in self.entries:
            if entry.name == name:
                return entry
        return None

    def extend(self, entries: Iterable[Entry]) -> 'Library':
        """A library with ``entries`` added.  The original is untouched."""
        return Library(self.entries + tuple(entries))

    def withPreviews(self) -> 'Library':
        """A copy with each entry's picture filled in where one can be found.

        **Fetches the sample catalogue** (once, cached on disk), so call it off
        the render thread.  An entry that already names a picture keeps it, and
        being offline simply leaves the rest without one.
        """
        try:
            urls = screenshot_urls()
        except Exception:
            return self
        return Library(
            entry if entry.preview else replace(
                entry, preview=urls.get(entry.name, ''))
            for entry in self.entries)


@lru_cache(maxsize=1)
def screenshot_urls() -> Dict[str, str]:
    """Sample name -> reference screenshot URL, from the Khronos catalogue.

    Memoised for the life of the process: the catalogue is one document and the
    library asks for it every time a shelf is opened.
    """
    from OpenGLContext.loaders import gltf
    return {str(entry['name']): str(entry['screenshot_url'])
            for entry in gltf.fetch_sample_catalog()
            if entry.get('name') and entry.get('screenshot_url')}


def _category_for(spec: Any) -> str:
    """Which shelf a demo-roster scene belongs on, from what the roster says.

    Derived rather than declared: the table says which entries are conformance
    fixtures; a scene with baked cameras or an explicit interior eye is a
    *place*; one whose materials need a lit environment is a material study; one
    built beside this checkout is a local build.  Everything else is a model.
    """
    from OpenGLContext.loaders import resolver
    if spec.feature_test:
        return FEATURE_TESTS
    if spec.source == '@parthenon':
        return LOCAL
    if spec.cameras or spec.look_at is not None:
        return SCENES
    if spec.source and not resolver.is_url(spec.source):
        return LOCAL
    if spec.needs_lit_backdrop:
        return MATERIALS
    return MODELS


def _options_for(spec: Any) -> Dict[str, Any]:
    """The viewer options a demo-roster scene records for itself.

    Not ``anim_time``: that pins an animation to one instant so a *capture* is
    reproducible, and carrying it into a viewer freezes the model where it
    stands.  The roster is shared with the capture harness, so what it records
    is not all meant for here.
    """
    options: Dict[str, Any] = {}
    for name in ('yaw', 'elevation', 'tilt', 'margin'):
        value = getattr(spec, name, None)
        if value:
            options[name] = value
    if spec.background:
        options['background'] = spec.background
    if spec.eye is not None:
        options['eye'] = spec.eye
    if spec.look_at is not None:
        options['look_at'] = spec.look_at
    return options


def sample_entries() -> Tuple[Entry, ...]:
    """The demo roster as library entries, in its own order.

    A Khronos sample's ``source`` is **its URL**, not its name.  A bare name is
    neither a path nor a URL, so a viewer handed one answers "file not found";
    the URL is a ``.glb`` the glTF adapter fetches and caches like any other,
    and it needs no special case anywhere.
    """
    from OpenGLContext.loaders import gltf, gltf_demos
    entries = []
    for spec in gltf_demos.iter_scenes():
        source = spec.source
        if source is None:
            source = gltf.sample_model_url(spec.name)
        elif source == '@parthenon':
            source = gltf_demos.find_parthenon() or ''
        if not source:
            continue                            # a local build that is not here
        entries.append(Entry(name=spec.name, source=source,
                             category=_category_for(spec),
                             note=spec.description,
                             options=_options_for(spec)))
    return tuple(entries)


def world_entries(directory: Optional[str] = None) -> Tuple[Entry, ...]:
    """The VRML97 worlds in ``directory`` as library entries.

    **Not part of the default shelf.**  The only ``.wrl`` files this project
    carries are ``tests/wrls``, and those are test data -- degenerate meshes,
    deliberately broken PNGs, one file per parser case -- rather than anything
    worth browsing, and they do not ship with the package at all.

    Kept because it is exactly what an application with worlds of its own
    wants: point it at them and :meth:`Library.extend` the result.
    """
    import glob
    import os
    if directory is None:
        return ()
    found = []
    for path in sorted(glob.glob(os.path.join(directory, '*.wrl'))):
        found.append(Entry(name=os.path.splitext(os.path.basename(path))[0],
                           source=path, category=WORLDS))
    return tuple(found)


def default_library() -> Library:
    """Everything this installation can offer, with no pictures yet.

    The glTF sample roster, and nothing else: this project ships no worlds of
    its own, and its ``tests/wrls`` are test data rather than content.  An
    application adds its own with :meth:`Library.extend` -- see
    :func:`world_entries`.

    Local and instant: call :meth:`Library.withPreviews` off the render thread
    when the pictures are wanted.
    """
    return Library(sample_entries())
