"""Provides function generating a "real world" time signature

Note:
    This is wall-clock, not CPU time, and uses
    the less-accurate time.time() function, even on
    Win32 systems.
"""
import time, sys

def systemTime():
    """Generate a "real-world" time value"""
    return time.time()