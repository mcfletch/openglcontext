# Python Modernization Plan

## Goal

Modernize OpenGLContext to require Python 3.10+ and remove all Python 2.7 compatibility code.

## Rationale

- Python 2.7 reached end-of-life in January 2020
- Modern Python features (type hints, dataclasses, walrus operator, match statements) improve code quality
- Removing compatibility shims simplifies the codebase
- Modern Python has better performance and security

## Changes Required

### Phase 1: Update Requirements

1. Update `setup.py` to require `python_requires='>=3.10'`
2. Update any CI/CD configurations
3. Update documentation to reflect Python 3.10+ requirement

### Phase 2: Remove Compatibility Code

1. Remove `from __future__ import` statements (print_function, division, etc.)
2. Remove any `six` library usage
3. Remove `if sys.version_info` checks
4. Convert `super(ClassName, self)` to `super()`
5. Remove string-based metaclass syntax

### Phase 3: Adopt Modern Python Features

1. Add comprehensive type hints throughout the codebase
2. Use `dataclasses` where appropriate for data containers
3. Use `pathlib.Path` instead of `os.path` where appropriate
4. Use f-strings consistently (already mostly done)
5. Use `typing.Protocol` for structural subtyping where appropriate

### Phase 4: Code Quality

1. Add `py.typed` marker for PEP 561 compliance
2. Configure `mypy` for type checking
3. Add pre-commit hooks for linting

## Files Likely Needing Changes

A grep for Python 2 compatibility patterns would identify specific files, but common patterns include:

- `from __future__ import print_function`
- `from __future__ import division`
- `from __future__ import absolute_import`
- `super(ClassName, self).__init__()`
- `isinstance(x, basestring)`
- `xrange`
- `raw_input`
- `dict.iteritems()`, `dict.iterkeys()`, `dict.itervalues()`

## Testing

1. Run full test suite on Python 3.10+
2. Run type checker (mypy) on updated code
3. Verify all demos still work

## Dependencies

Some dependencies may need version updates to their Python 3-only versions.
