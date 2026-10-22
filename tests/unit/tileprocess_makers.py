"""Makers the tile process tests start in child processes."""
import os
import signal
import time

import numpy as np


class Maker:
    """Answers each key with its process id, and an array the key decides."""

    def __init__(self, delay: float = 0.0) -> None:
        self.delay = delay

    def make(self, key):
        if key == 'boom':
            raise ValueError('no tile %s' % key)
        if key == 'die':
            os._exit(3)
        if key == 'interrupt':
            os.kill(os.getpid(), signal.SIGINT)
            time.sleep(5.0)
        time.sleep(self.delay)
        return os.getpid(), np.full((200, 300), float(key), dtype='f')


def broken_factory():
    raise RuntimeError('cannot build the maker')
