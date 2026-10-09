"""X3D's and VRML97's Anchor: a group whose geometry, clicked, follows its url

The Anchor is reached by the pointer as the pointing-device sensors are
(:mod:`OpenGLContext.scenegraph.x3dpointing`): pressing the primary button
over its geometry and releasing it there calls
``context.OnAnchor(anchor, url, parameter)``, which the context answers
(:meth:`OpenGLContext.context.ContextCore.OnAnchor`).

Where each url leads is :func:`anchor_targets`, X_ITE's reading of an
Anchor: ``#name``, or the document's own name with ``#name``, binds that
viewpoint; another X3D or VRML document the document may reach (the
resolver's rules, :doc:`untrusted`) is loaded in place of the world, binding
the viewpoint its fragment names; a page (``.html``, ``.htm``, ``.xhtml``), a
document the rules refuse, or any url with a ``target=`` parameter other than
``_self`` goes to the application.

An Anchor reads nothing until it is followed, so a LoadSensor watching one
reads it as loaded, as X_ITE does.
"""
import logging
import os
from collections.abc import Sequence
from typing import Any, NamedTuple, Optional

from vrml import protofunctions
from vrml.vrml97 import basenodes
from vrml.x3d import loadsensor

from OpenGLContext.scenegraph import grouping

log = logging.getLogger(__name__)

__all__ = ['Anchor', 'AnchorTarget', 'PAGE_SUFFIXES', 'anchor_targets', 'follow', 'target_of']

#: The ends of a url naming a page for a web browser rather than a world.
PAGE_SUFFIXES = ('.html', '.htm', '.xhtml')


class AnchorTarget(NamedTuple):
    """Where one of an Anchor's urls leads

    kind -- ``'viewpoint'``: bind :attr:`viewpoint` in the Anchor's scene;
        ``'world'``: load :attr:`url` in place of the world, then bind
        :attr:`viewpoint` where it is not empty; ``'elsewhere'``: :attr:`url`
        as the document wrote it, for the application
    url -- the resolved location of a world; the url as written for elsewhere
    viewpoint -- the name after ``#``
    target -- the ``target=`` parameter
    """

    kind: str
    url: str
    viewpoint: str
    target: str


def target_of(parameter: Any) -> str:
    """The value of the first ``target=`` entry of an Anchor's `parameter`; ''"""
    for entry in parameter or ():
        name, _, value = str(entry).partition('=')
        if name.strip().lower() == 'target':
            return value.strip()
    return ''


def anchor_targets(anchor: Any, url: Any, parameter: Any) -> list[AnchorTarget]:
    """Where each of `url` leads from `anchor`, in order; no I/O

    Relative urls resolve against the Anchor's document under the resolver's
    rules (:func:`~OpenGLContext.scenegraph.audio.document_resolver`); an
    Anchor built in code, with no document, reads them as they are.
    """
    from OpenGLContext.scenegraph.audio import document_resolver  # noqa: PLC0415 the audio module imports nodes
    target = target_of(parameter)
    confine = document_resolver(anchor) if anchor is not None else None
    root = protofunctions.root(anchor) if anchor is not None else None
    base = str(getattr(root, 'baseURI', '') or '')
    found = []
    for entry in url or ():
        written = str(entry).strip()
        if not written:
            continue
        location, _, fragment = written.partition('#')
        if not location:
            found.append(AnchorTarget('viewpoint', '', fragment, target))
            continue
        resolved = location
        if confine is not None:
            try:
                resolved = str(confine.resolve(location))
            except (OSError, ValueError):
                found.append(AnchorTarget('elsewhere', written, fragment, target))
                continue
        if fragment and base and _same_document(resolved, base):
            found.append(AnchorTarget('viewpoint', '', fragment, target))
        elif target not in ('', '_self') or location.lower().endswith(PAGE_SUFFIXES):
            found.append(AnchorTarget('elsewhere', written, fragment, target))
        else:
            found.append(AnchorTarget('world', resolved, fragment, target))
    return found


def follow(context: Any, anchor: Any, targets: Sequence[AnchorTarget]) -> bool:
    """Follow the first of `targets` that leads somewhere, for `context`; whether one did

    A viewpoint is bound in ``context.getSceneGraph()``. A world is read by
    ``context.sceneLoader`` and becomes ``context.sg``, binding its fragment's
    viewpoint; where it does not load, the targets after it are followed.
    Anything else goes to ``context.OnAnchorElsewhere(anchor, url, target)``.
    """
    for index, found in enumerate(targets):
        if found.kind == 'viewpoint':
            if _bind(context, context.getSceneGraph(), found.viewpoint):
                return True
            log.info('Anchor viewpoint %r names no node of the scene', found.viewpoint)
        elif found.kind == 'world':
            _load(context, anchor, found, list(targets[index + 1:]))
            return True
        elif context.OnAnchorElsewhere(anchor, found.url, found.target):
            return True
    return False


def _load(context: Any, anchor: Any, found: AnchorTarget, rest: list[AnchorTarget]) -> None:
    """Read `found`'s world in the background; the rest are followed if it fails"""

    def loaded(request: Any) -> None:
        context.sg = request.result
        _bind(context, context.sg, found.viewpoint)
        context.triggerRedraw(1)

    def failed(request: Any) -> None:
        log.warning('Anchor url %r did not load', found.url)
        follow(context, anchor, rest)

    context.sceneLoader.load(found.url, on_loaded=loaded, on_failed=failed)


def _bind(context: Any, graph: Any, name: str) -> bool:
    """Bind the viewpoint `graph` names `name`; whether there was one"""
    viewpoint = graph.getDEF(name) if graph and name else None
    if viewpoint is None:
        return False
    viewpoint.set_bind = True
    context.triggerRedraw(1)
    return True


def _same_document(location: str, base: str) -> bool:
    if '://' in base:
        return location == base
    return os.path.abspath(location) == os.path.abspath(base)


class Anchor(grouping.Grouping, basenodes.Anchor):
    """A group that follows its url when its geometry is clicked

    Reference:
        https://www.web3d.org/specifications/X3Dv4Draft/ISO-IEC19775-1v4.1-CD/Part01/components/networking.html#Anchor
    """

    def loadState(self) -> str:
        """Loaded: an Anchor has nothing to read until it is followed"""
        return loadsensor.LOADED

    def bind(self, context: Any) -> bool:
        """Have `context`'s pointer reach this Anchor"""
        from OpenGLContext.scenegraph import x3dpointing
        x3dpointing.sensing(context)
        return True

    # The pointer, as x3dpointing.PointerSensing tells a sensor of it.

    def pointerOver(self, hit: Optional[Any]) -> None:
        """The pointer has moved over the Anchor's geometry or off it"""

    def pointerPress(self, hit: Any, ray: Any) -> None:
        """The button has gone down over the Anchor's geometry"""

    def pointerDrag(self, hit: Optional[Any], ray: Any) -> None:
        """The pointer has moved with the button held"""

    def follow(self, context: Any) -> Any:
        """Ask `context` to follow this Anchor's url"""
        return context.OnAnchor(self, list(self.url), list(self.parameter))
