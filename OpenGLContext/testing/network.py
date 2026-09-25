"""Whether a remote asset can be had here, asked without fetching it.

A test that reads a published sample -- a Khronos model, a Poly Haven
panorama -- needs a copy in the resolver's cache or a connection to the host
that serves it. :func:`unreachable` answers that before the test fetches
anything, so the fetch itself runs unguarded and a defect in the loader fails
the test rather than reading as a machine that is offline::

    from OpenGLContext.testing.network import unreachable

    def test_the_duck_loads():
        reason = unreachable(DUCK_URL)
        if reason:
            pytest.skip(reason)
        scene = load(fetch_to_cache(DUCK_URL))
        ...

A host's answer is kept for the life of the process.
"""
from __future__ import annotations

import os
import socket
import urllib.parse
from typing import Dict, Optional, Tuple

#: Seconds to wait for a host to accept a connection.
CONNECT_TIMEOUT = 5.0

#: Why each (host, port) asked about could not be reached, or ``None`` where it
#: could.
_HOSTS: Dict[Tuple[str, int], Optional[str]] = {}


def unreachable(url: str, cache_dir: str | None = None) -> str | None:
    """Why ``url`` cannot be fetched here, or ``None`` where it can.

    ``None`` where the resolver's cache in ``cache_dir`` (by default its
    per-user one) already holds the URL, or where the URL's host accepts a
    connection on its port.
    """
    from OpenGLContext.loaders.resolver import cached_path

    if os.path.exists(cached_path(url, cache_dir)):
        return None
    parts = urllib.parse.urlsplit(url)
    host = parts.hostname or ''
    port = parts.port or (443 if parts.scheme == 'https' else 80)
    if (host, port) not in _HOSTS:
        _HOSTS[host, port] = _connection_refused(host, port)
    refused = _HOSTS[host, port]
    if refused is None:
        return None
    return '%s is not cached and cannot be fetched: %s' % (url, refused)


def _connection_refused(host: str, port: int) -> str | None:
    """Why no connection to ``host`` on ``port`` could be opened, or ``None``."""
    try:
        socket.create_connection((host, port), timeout=CONNECT_TIMEOUT).close()
    except OSError as err:
        return 'no connection to %s:%d (%s)' % (host, port, err)
    return None
