'''Retained-mode object hierarchy based (loosely) on VRML 97 nodes

This package provides "retained-mode" objects which can be
easily rendered within OpenGLContext Contexts.

The implementations of the objects are fairly straightforward
with the idea that users will browse the source of the objects
to see how they can implement similar functionality in their own
systems.  There is little optimization in the nodes provided.

Note that much of the work of rendering is accomplished by the
rendervisitor module, rather than individual nodes.  The node-
classes merely have the node-specific customisations needed to
support their individualised operation.

References:
    VRML 97 International Standard
    http://www.web3d.org/x3d/specifications/vrml/ISO-IEC-14772-IS-VRML97WithAmendment1/
'''