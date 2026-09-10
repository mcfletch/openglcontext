"""Utility mechanism to watch for memory leaks over time

:func:`init` remembers everything the garbage collector can see; :func:`delta`
then answers what has appeared since, and folds it into the remembered set so
the next call reports only what is newer still.
"""
import gc
from typing import Any, Dict, List

#: Identity of every object seen so far, as ``{id(object): True}``.  Held by id
#: rather than by reference so that watching for a leak does not cause one.
whole_set: Dict[int, bool] = {}


def init() -> None:
    """Remember every object the collector can currently see"""
    for item in gc.get_objects():
        whole_set[id(item)] = True


def delta(report: bool = True) -> List[Any]:
    """The objects that have appeared since the last :func:`init` or :func:`delta`

    ``report`` prints each one as it is found, which is what makes this usable
    from a key binding in a running context.
    """
    new = []
    for item in gc.get_objects():
        if not whole_set.get(id(item)):
            new.append(item)
            if report:
                print('new', type(item), item)
        whole_set[id(item)] = True
    return new
