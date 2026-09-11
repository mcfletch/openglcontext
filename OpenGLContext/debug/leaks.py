"""Utility mechanism to watch for memory leaks over time

:func:`init` remembers everything the garbage collector can see; :func:`delta`
then answers what has appeared since, and remembers what is there now so the
next call reports only what is newer still.

Objects are remembered by ``id()`` rather than by reference, so that watching
for a leak does not cause one.  An id names an object only while that object
is alive -- CPython hands a freed object's memory to the next object made -- so
what is remembered is exactly what was alive at the last call, never an id left
over from before it.  One case is out of reach without holding references: an
object alive at the last call, freed since, whose memory a new object has taken
before the next call.  That new object is taken for the old one.
"""
import gc
from typing import Any, Dict, List

#: Identity of every object alive at the last :func:`init` or :func:`delta`,
#: as ``{id(object): True}``.
whole_set: Dict[int, bool] = {}


def _remember(objects: List[Any]) -> None:
    """Make the remembered set exactly the identities of `objects`"""
    whole_set.clear()
    whole_set.update(dict.fromkeys(map(id, objects), True))


def init() -> None:
    """Remember every object the collector can currently see, and nothing else"""
    _remember(gc.get_objects())


def delta(report: bool = True) -> List[Any]:
    """The objects that have appeared since the last :func:`init` or :func:`delta`

    ``report`` prints each one as it is found, which is what makes this usable
    from a key binding in a running context.
    """
    objects = gc.get_objects()
    new = [item for item in objects if id(item) not in whole_set]
    if report:
        for item in new:
            print('new', type(item), item)
    _remember(objects)
    return new
