"""Ruff rules that hold across the whole package.

The package still carries lint debt in its oldest modules, so a full ``ruff
check`` is not yet a gate.  These rules are the ones that *are* clear, each
covering a class of defect rather than a matter of layout -- a name used but
never imported, a format string whose arguments do not match it, an exception
class that cannot be raised.  A rule joins this list once the package is clean
of it, and the gate then keeps it that way.

See ``plans/LINT-AND-TYPING.md`` for the rules still to be cleared.
"""
import subprocess
import sys

import pytest

from OpenGLContext.testing.paths import tests_root

ROOT = tests_root(__file__).parent
PACKAGE = ROOT / 'OpenGLContext'

RULES = [
    'B006',  # mutable-argument-default
    'F402',  # import-shadowed-by-loop-var
    'F501',  # invalid-%-format literals, through F509
    'F502',
    'F503',
    'F504',
    'F506',
    'F507',  # %-format placeholder/argument count mismatch
    'F508',
    'F509',
    'F521',  # .format() call errors, through F525
    'F522',
    'F524',
    'F525',
    'F821',  # undefined-name
    'F901',  # raise NotImplemented
]


@pytest.mark.parametrize('rule', RULES)
def test_package_is_clean_of(rule):
    """No file in the package trips ``rule``."""
    finished = subprocess.run(
        [
            sys.executable, '-m', 'ruff', 'check',
            '--no-cache', '--output-format=concise', '--select', rule, str(PACKAGE),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    assert finished.returncode == 0, finished.stdout or finished.stderr
