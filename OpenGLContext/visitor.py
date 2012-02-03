"""Traversal objects for Contexts and scenegraphs
"""
from OpenGLContext.scenegraph import nodepath
import sys, traceback, types
from vrml.vrml97 import nodetypes
from vrml import node
import logging
log = logging.getLogger( __name__ )

DEBUG_VISIT_METHOD = 0
if DEBUG_VISIT_METHOD:
    log.setLevel( DEBUG )

TRAVERSAL_TYPES = (nodetypes.Traversable, nodetypes.Children, node.PrototypedNode, nodetypes.Rendering)

def parents( c, seen=None ):
    """Python class base-finder"""
    if type( c ) == types.ClassType:
        if hasattr(c,'_old_style_class_parents_'):
            return c._old_style_class_parents_
        if seen is None:
            seen = {}
            setLocal = 1
        else:
            setLocal = 0
        seen[c] = None
        items = [c]
        for base in c.__bases__:
            if not base in seen:
                items.extend( parents(base, seen))
        if setLocal:
            c._old_style_class_parents_ = items
        return items
    else:
        return list(c.__mro__) 	

class Visitor( object ):
    """Extremely basic visitor/traversal object for scenegraphs

    The "visitor" does not actually follow the classic visitor
    pattern (where the nodes dispatch the visitor to their
    children).  Instead, it is a traversal mechanism that has
    four major points of customisation:

        vmethods -- virtual methods which are applied to a node
            during traversal.  Each applicable vmethod (is
            registered as a method for one of the node's
            parent classes) is applied _in turn_, so it is
            possible to have large numbers of vmethods called
            for any given node.  Return values are callable
            tokens which perform any state-resetting required

            See: buildVMethods
            
        preVisit -- called for _every_ node before visiting, if it
            returns a false value, then the node's vmethods
            and children are _not_ processed.
            
        postVisit -- called for _every_ node where preVisit
            returned a true value as the last customisation point
            before the visitor finished processing the node.

    Note: For the purposes of the visitor, a Context is just a
    node like any other.  It produces a single "child" node which
    is either a scenegraph or a special node which calls the Context's
    Render method.

    There is a log associated with the visitors which will log the
    particular nodes, their vmethods, and any finalisation tokens
    being run.  By default this log is set to WARN level.  You can
    set it to INFO to see the verbose trace (warning, this will
    seriously slow down your rendering on many systems!)  The
    logging calls are eliminated (regardless of the logging setting)
    under a python -O or python -OO run.
    """
    def __init__( self ):
        """Initialise the visitor object

        calls self.buildVMethods() then builds the current
        stack.

        Attributes:
            currentStack -- nodepath describing the current
                processing stack for this visitor

            _vmethods -- mapping from class/superclass to
                methods to be applied on entry to any instance
                of the class, see the vmethods method,
                (multiple match)
        """
        self.buildVMethods()
        self.currentStack = nodepath.NodePath()
    def buildVMethods( self ):
        """Customization point: Create application-specific type:method-name mapping

        Basically this lets you call a named method for each
        class/base-class in a node's __mro__.  Override this (calling
        the base implementation and modifying the resulting dictionary)
        to register your particular virtual methods.

        Format is:
            class-pointer: string-method-name

        The dictionary is stored as self._vmethods
        """
        self._vmethods = {}
        return self._vmethods
    def vmethods( self, obj ):
        """Get all relevant "virtual methods" as unbound methods

        Returns *all* registered vmethods for the classes in the
        given object's class's __mro__

        This version caches the unbound methods in a per-visitor-
        class dictionary, which should make it at least a little
        faster.
        """
        cls = type(self)
        objType = obj.__class__
        if not '_visitor_cmethods' in cls.__dict__:
            setattr(cls, '_visitor_cmethods', {})
        try:
            return self._visitor_cmethods[ objType ]
        except (KeyError):
            names = filter(
                None,
                map(self._vmethods.get, parents(obj.__class__))
            )
            self._visitor_cmethods[ objType ] = [getattr(cls,name) for name in names]
            return self._visitor_cmethods[ objType ]

    def children( self, node, types=TRAVERSAL_TYPES ):
        """Get children to visit for a node

        Determine the set of children to be visited for
        a given node in the node graph.  If the node
        has a method renderedChildren, it will be called
        with types as an argument and the result returned
        as the sequence of children.
        """
        if hasattr( node, 'renderedChildren'):
            return node.renderedChildren( types )
        return ()
    if DEBUG_VISIT_METHOD:
        def visit( self, node ):
            """Visit an individual node, dispatch to methods as necessary

            The visiting algorithm is fairly involved compared
            to the classic computer science Visitor algorithm.

            First we call self.preVisit( node ), and if the
            result of that is true, we continue processing.
            This allows you to use preVisit to do such things
            as processing every node in the scenegraph.

            If we are visiting the node: (preVisit returned true)
            
                * add the node to self.currentStack
                * retrieve the "vmethods" for the node
                * call each vmethod with the node as argument
                    o if the vmethod returns a finalization token
                        we store that token for finalization
                * we determine the children to visit for the node
                * for each child, we call visit recursively
                * during finalization (after children are finished
                    processing)
                    o if we have any finalization tokens, we call
                        those tokens
                    o we call self.postVisit( node )
                    o we restore the previous self.currentStack
            """
            if __debug__:
                log.info(
                    'start visit( %s ) id=%s depth=%s',
                    node,
                    id(node),
                    len(self.currentStack),
                )
            tokens = None
            previousStack = self.currentStack
            self.currentStack = self.currentStack + (node,)
            try:
                for method in self.vmethods(node):
                    try:
                        if __debug__:
                            log.info(
                                'run method %s for node %s',
                                repr(method),
                                node,
                            )
                        token = method( self, node )
                        if token is not None:
                            if not tokens:
                                tokens = [token]
                            else:
                                tokens.append( token )
                    except:
                        traceback.print_exc( )
                        log.error(
                            """method %s for node %s""",
                            method,
                            node,
                        )
                try:
                    children = self.children( node )
                except:
                    traceback.print_exc( )
                    log.error(
                        """exception in children method for node %s""",
                        node,
                    )
                else:
                    for child in children:
                        self.visit( child )
            finally:
                try:
                    if tokens:
                        for token in tokens:
                            if __debug__:
                                log.info(
                                    'run post-processing token %s for node %s',
                                    repr(token),
                                    node,
                                )
                            token( self )
                finally:
                    self.currentStack = previousStack
                    if __debug__:
                        log.info(
                            'end visit( %s ) depth=%s',
                            node,
                            len(previousStack),
                    )
    else: #DEBUG_VISIT_METHOD is false, use non-instrumented version...
        def visit( self, node ):
            """Visit an individual node, dispatch to methods as necessary

            The visiting algorithm is fairly involved compared
            to the classic computer science Visitor algorithm.

            First we call self.preVisit( node ), and if the
            result of that is true, we continue processing.
            This allows you to use preVisit to do such things
            as processing every node in the scenegraph.

            If we are visiting the node: (preVisit returned true)
            
                * add the node to self.currentStack
                * retrieve the "vmethods" for the node
                * call each vmethod with the node as argument
                    o if the vmethod returns a finalization token
                        we store that token for finalization
                * we determine the children to visit for the node
                * for each child, we call visit recursively
                * during finalization (after children are finished
                    processing)
                    o if we have any finalization tokens, we call
                        those tokens
                    o we call self.postVisit( node )
                    o we restore the previous self.currentStack
                    
            Note: this is the "production" version of visit
            which only logs errors, not "info" level traces,
            this avoids the 100's of 1000's of calls generated
            by the huge number of iterations.
            """
            tokens = None
            previousStack = self.currentStack
            self.currentStack = self.currentStack + [node]
            try:
                for method in self.vmethods(node):
                    try:
                        token = method( self, node )
                        if token is not None:
                            if not tokens:
                                tokens = [token]
                            else:
                                tokens.append( token )
                    except:
                        traceback.print_exc( )
                        log.error(
                            """method %s for node %s""",
                            method,
                            node,
                        )
                try:
                    children = self.children( node )
                except:
                    traceback.print_exc( )
                    log.error(
                        """exception in children method for node %s""",
                        node,
                    )
                else:
                    for child in children:
                        try:
                            self.visit( child )
                        except Exception:
                            traceback.print_exc()
                            log.error(
                                """exception visiting child %s""",
                                child,
                            )
            finally:
                try:
                    if tokens:
                        for token in tokens:
                            token( self )
                finally:
                    self.currentStack = previousStack

class _Finder( Visitor ):
    """Traverse a scenegraph looking for bindable nodes

    This is a simple implementation of a scenegraph-search
    which looks for all nodes which are instances of any of
    a given set of classes/types.

    Attributes:
        result -- the resulting set of node-paths
        desiredTypes -- the node-types being searched for

    See the find function for the normal usage API
    """
    def __init__(
        self,
        desiredTypes=(),
    ):
        """Initialize the _Finder object

        desiredTypes -- sequence of types to be searched for
        """
        self.desiredTypes = desiredTypes
        self.result = []
        super(_Finder, self).__init__()
    def visit( self, node ):
        """Visit an individual node, search for self.desiredTypes

        This is a heavily trimmed version of the superclass method
        """
        todo = [(0,node)]
        currentStack = []
        childrenTypes = TRAVERSAL_TYPES + self.desiredTypes
        while todo:
            index, node = todo[0]
            del todo[0]
            del currentStack[index:]
            is_desired = isinstance( node, self.desiredTypes )
            try:
                children = self.children( node, types=childrenTypes )
            except:
                traceback.print_exc( )
                log.error(
                    """exception in children method for node %s""",
                    node,
                )
            else:
                stack_length = len(currentStack)
                new_items = [
                    (stack_length+1,child)
                    for child in children
                ]
                if is_desired or new_items:
                    currentStack.append( node )
                    if is_desired:
                        self.result.append( 
                            nodepath.NodePath(tuple(currentStack)) 
                        )
                    if new_items:
                        todo[0:0]=new_items

def find( sg, desiredTypes = ()):
    """Get list of node-paths to instances of desiredTypes

    desiredTypes -- sequence of desired base types

    returns node-paths for each node in the scenegraph
    of the given types

    Note:
        The traversal is the same as that used by the
        rendering procedure, so is quite possible for
        non-rendering nodes to be missed by the search.
    """
    if not isinstance( desiredTypes, tuple ):
        desiredTypes = (desiredTypes, )
    f = _Finder( desiredTypes )
    f.visit( sg )
    return f.result
