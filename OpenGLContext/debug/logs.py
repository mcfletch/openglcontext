"""Formatting an exception for a log message"""
import sys
import traceback
from typing import Any, Optional


def getTraceback(error: Optional[Any] = None) -> str:
    """Get the formatted traceback of the exception being handled

    With no exception in flight -- a caller holding an error object it did not
    catch here -- the error's own text is what comes back, since a traceback
    for it is not available to ask for.
    """
    if sys.exc_info()[0] is None:
        return str(error)
    try:
        return traceback.format_exc(10)
    except Exception:
        return str(error)
