"""Pictures on the screen: decoded off the draw call, and bounded.

A skin's own artwork is a handful of small files needed for the first frame, and
loading those where they are asked for is right.  A **gallery** is not: a library
of a few hundred models is a few hundred screenshots, several megabytes each,
often at the end of a URL -- and decoding one inside the draw call that first
shows it is a visible stutter every time the selection moves, while keeping all
of them is a texture budget that only grows.

So this cache does three things the naive one did not:

* **Decodes on a worker thread and uploads on the render thread.**  GL is
  single-threaded, so the split is exactly there: the worker produces pixels,
  :meth:`PictureCache.pump` turns them into textures, once a frame.
* **Fetches an http(s) URL** through the security-hardened resolver, which caps
  the size and caches it on disk, so a picture is downloaded once ever rather
  than once a session.
* **Evicts the least recently used** once a texel budget is reached, so
  scrolling through a thousand entries costs a bounded amount of card memory.

Nothing here calls GL itself -- uploading and deleting are two callables handed
in -- which is what makes the whole thing testable without a window.
"""
from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from typing import Any, Callable, List, Optional, Tuple

from OpenGLContext.loaders.resolver import fetch_to_cache, is_url

log = logging.getLogger(__name__)

__all__ = ['PictureCache', 'DEFAULT_BUDGET', 'UPLOADS_PER_PUMP']

#: Resident texels before the least recently used are dropped.  64M texels is
#: 256 MB at RGBA8 -- room for a large gallery, and far below what a card that
#: can render any of these models has.
DEFAULT_BUDGET = 64 * 1024 * 1024

#: Textures created per :meth:`PictureCache.pump`.  A whole gallery arriving at
#: once must not cost one long frame; a few per frame is invisible.
UPLOADS_PER_PUMP = 2

#: Threads decoding pictures.  Two is enough to keep ahead of someone scrolling
#: and few enough not to matter to the render thread.
DEFAULT_WORKERS = 2

#: An entry: the texture, and the size it was decoded at.
Entry = Tuple[Any, int, int]


class PictureCache(object):
    """Textures for pictures, loaded when they can be and dropped when they must.

    ``upload(width, height, rgba)`` and ``delete(texture)`` are the only two
    things it cannot do itself; both are called on whichever thread calls
    :meth:`pump` or :meth:`clear`, which is the render thread.

    ``workers=0`` decodes on the calling thread instead of on a pool, which is
    what a caller with no use for threads -- and every test -- wants.

    ``onReady`` is how a picture that has arrived gets itself drawn; see the
    attribute of the same name.
    """

    def __init__(self, upload: Callable[[int, int, bytes], Any],
                 delete: Callable[[Any], None],
                 budget: int = DEFAULT_BUDGET,
                 workers: int = DEFAULT_WORKERS,
                 uploadsPerPump: int = UPLOADS_PER_PUMP,
                 cacheDirectory: Optional[str] = None,
                 onReady: Optional[Callable[[], None]] = None) -> None:
        self.upload = upload
        self.delete = delete
        #: Called, off the render thread, when a picture has been decoded and
        #: is waiting to be uploaded.  A context that only draws when something
        #: asks it to has no other way of knowing there is anything new to
        #: show, and the picture then appears whenever the next unrelated event
        #: happens to cause a frame -- which reads as a very slow load of a
        #: file that took a tenth of a second to fetch.
        self.onReady = onReady
        self.budget = budget
        self.uploadsPerPump = uploadsPerPump
        self.cacheDirectory = cacheDirectory
        #: How many pictures could not be read.  Each is attempted once.
        self.failures = 0
        self._lock = threading.Lock()
        #: url -> entry, in least-recently-used order.
        self._resident: "OrderedDict[str, Entry]" = OrderedDict()
        #: Texels held by :attr:`_resident`, kept rather than recomputed.
        self._texels = 0
        #: url -> (width, height, rgba) waiting for the render thread.
        self._decoded: "OrderedDict[str, Tuple[int, int, bytes]]" = OrderedDict()
        #: urls being decoded, or known bad.
        self._working: set = set()
        self._bad: set = set()
        self._pool = self._makePool(workers)

    @staticmethod
    def _makePool(workers: int) -> Any:
        if workers <= 0:
            return None
        from concurrent.futures import ThreadPoolExecutor
        return ThreadPoolExecutor(max_workers=workers,
                                  thread_name_prefix='oglc-pictures')

    # -- asking -----------------------------------------------------------
    def get(self, url: Optional[str], blocking: bool = False) -> Optional[Entry]:
        """The texture for ``url``, or None if it is not ready (or never will be).

        Returns None on the first ask and starts the picture loading; a later
        frame gets it.  ``blocking=True`` loads it here and now instead, which is
        what a caller whose *first* frame needs it -- a skin's own artwork --
        should use.
        """
        if not url:
            return None
        with self._lock:
            found = self._resident.get(url)
            if found is not None:
                self._resident.move_to_end(url)
                return found
            if url in self._bad:
                return None
        if blocking:
            self._decode(url)
            self._pump(1)
            with self._lock:
                return self._resident.get(url)
        self._request(url)
        return None

    def _request(self, url: str) -> None:
        """Start loading ``url`` unless something already is."""
        with self._lock:
            if url in self._working or url in self._decoded:
                return
            self._working.add(url)
        if self._pool is None:
            self._decode(url)
        else:
            self._pool.submit(self._decode, url)

    # -- loading (worker thread) ------------------------------------------
    def _decode(self, url: str) -> None:
        """Fetch and decode ``url`` into pixels.  **No GL here.**"""
        try:
            pixels = self._read(url)
        except Exception:
            log.warning("could not load picture %s", url, exc_info=True)
            with self._lock:
                self._bad.add(url)
                self._working.discard(url)
                self.failures += 1
            return
        with self._lock:
            self._decoded[url] = pixels
            self._working.discard(url)
        if self.onReady is not None:
            self.onReady()          # outside the lock: it will ask for a frame

    def _read(self, url: str) -> Tuple[int, int, bytes]:
        """``(width, height, rgba)`` for a path or an http(s) URL.

        **Flipped top-to-bottom on the way in.**  PIL hands over its rows top
        first and a GL texture's ``v`` runs bottom up, so the bytes as they come
        put every picture on its head.  Turning them here rather than at each
        draw means one flip per picture instead of one per frame, and means
        every caller -- a skin's nine-slice, a gallery, a thumbnail -- is the
        right way up without knowing this was ever a question.
        """
        from PIL import Image, ImageOps
        from OpenGLContext.loaders.loader import local_path
        if is_url(url):
            path = fetch_to_cache(url, cache_dir=self.cacheDirectory)
        else:
            path = local_path(url)
        image = Image.open(path).convert('RGBA')
        width, height = image.size
        return width, height, ImageOps.flip(image).tobytes()

    def waitForPending(self, timeout: float = 5.0) -> bool:
        """Block until nothing is being decoded.  For tests and for teardown.

        Returns whether the workers finished within ``timeout``; a caller that
        cannot wait longer carries on with whatever did arrive.
        """
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if not self._working:
                    return True
            time.sleep(0.005)
        return False

    # -- uploading (render thread) ----------------------------------------
    def pump(self, limit: Optional[int] = None) -> int:
        """Turn decoded pixels into textures.  Returns how many were made.

        Call once a frame, with a GL context current.  At most
        :attr:`uploadsPerPump` are made per call, so a gallery arriving all at
        once is spread over a few frames rather than stalling one.
        """
        return self._pump(self.uploadsPerPump if limit is None else limit)

    def _pump(self, limit: int) -> int:
        made = 0
        while made < limit:
            with self._lock:
                if not self._decoded:
                    break
                url, (width, height, rgba) = self._decoded.popitem(last=False)
            texture = self.upload(width, height, rgba)
            with self._lock:
                self._resident[url] = (texture, width, height)
                self._texels += width * height
            made += 1
            self._evict()
        return made

    def _evict(self) -> None:
        """Drop least-recently-used pictures until the budget is met.

        The newest is never dropped, even when it alone exceeds the budget: a
        picture too big to keep is still a picture somebody asked to see, and
        refusing to show it would be a worse answer than going over once.
        """
        while self._texels > self.budget:
            with self._lock:
                if len(self._resident) <= 1:
                    return
                url, (texture, width, height) = self._resident.popitem(last=False)
                self._texels -= width * height
            self.delete(texture)

    # -- letting go -------------------------------------------------------
    @property
    def resident(self) -> int:
        """How many pictures are on the card."""
        return len(self._resident)

    def clear(self) -> None:
        """Delete every texture.  The cache is usable again afterwards."""
        with self._lock:
            entries: List[Entry] = list(self._resident.values())
            self._resident.clear()
            self._decoded.clear()
            self._bad.clear()
            self._texels = 0
        for texture, _width, _height in entries:
            self.delete(texture)

    def close(self) -> None:
        """Stop the workers and release everything.  For context teardown."""
        pool, self._pool = self._pool, None
        if pool is not None:
            pool.shutdown(wait=False, cancel_futures=True)
        self.clear()
