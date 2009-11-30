"""Stencil-buffer-based shadowing implementation

From an article by Eric Lengyel in Gamasutra:
    http://www.gamasutra.com/features/20021011/lengyel_01.htm
and the related paper:
    http://developer.nvidia.com/docs/IO/2585/ATT/RobustShadowVolumes.pdf

Python implementation by Mike Fletcher.  Note that
this is not a direct translation of the original approach.

Also note that, although I'm trying to follow the examples,
most of the actual code in the article just wouldn't fly in
Python, so I tend to use a lot of Numeric Python functions
instead.

Usage:
    OpenGLContext.shadow.shadowcontext.ShadowContext is a
    mix-in class for Contexts which provides the necessary
    features for rendering shadows.

Notes:
    Only IndexedFaceSet nodes may cast shadows in the
    current implementation.

    Single-face edges are not supported, and will cause
    artifacts.

    There will be problems trying to render degenerate faces.
"""