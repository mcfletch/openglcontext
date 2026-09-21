OpenGLContext Event Model
=========================

.. rst-class:: introduction

This document describes the mechanisms within OpenGLContext which allow for
providing interactivity, both at the context and the scenegraph levels.  This
includes keyboard and mouse events, as well as timers and routes.

Features of the Event Model
---------------------------

There are a number of user-level features which are implemented by the "event
model" within OpenGLContext:

- field "watching" -- allows code to register callbacks for changes to given
  fields of given nodes

- cache updates/invalidation -- uses field watching (with some other techniques)
  to automatically update scenegraph caches to reflect updated content

- VRML 97-style routing tables -- allows construction of linked node structures
  so that updating fields of a particular node automatically update the linked
  fields

- mouse/keyboard/timer event-handler registration -- allows code to respond to
  user interaction, mouse events also allow for per-node registration, allowing
  composable interactive objects to be created

each of these features will be discussed below.

Dispatcher
----------

The PyDispatcher package is the primary mechanism used for event propagation
within OpenGLContext 2.0.  This module allows you to register functions to be
notified when "senders" send particular signals.  Each field of each node can
generate signals when setting and/or deleting field values for the node. 
Similarly, each event manager registers functions with the dispatcher which
are to be called when a particular event is received, then sends those events
when the event is actually received.

Field Watching
--------------

Fields generate signals by default on set or delete. Nothing generated during
parser-mediated instantiation save for prototyped nodes Normally not something
you want to use directly, but it is what much of the rest of the interaction
is built upon.

Cache Invalidation
------------------

Built upon field watching, nodes register dependencies on node, field pairs. 
If the node sends an update signal for that field, then the cache object is
invalidated, and the node regenerates its cache data during the next rendering
pass.

Routing Tables
--------------

Two major variants:

The ROUTE is a simple unidirectional channel through which updates to a
particular field of a particular node are propagated along the arc of the
route to the destination node, field pair.  This allows you to create routing
tables which tie together elements within a scenegraph so that code does not
need to explicitly chase down dependent fields, it can simply allow route
propagation to update the dependent fields.

The PROTO's IS mapping, which maps from a prototype node's fields to fields on
nodes within the prototype's internal scenegraph.  This is a bidirectional
linkage, where changing the prototype's fields updates the internal nodes, and
updating the internal node updates the prototype's corresponding field.

Event Handlers
--------------

Most contexts derive from the EventHandlerMixIn class, which provides a method
addEventHandler, which allows for registering event handlers for given event
types (specified as strings).  Individual EventHandler objects are responsible
for each event type, and are responsible for processing events of their own
type.  Most (currently all) EventHandler objects use the PyDispatcher module
to maintain the internal structures required to provide the registration
tables for the handler callbacks.

.. code-block:: python

   self.addEventHandler( "mousein", function = self.OnMouseIn )self.addEventHandler( "mouseout", function = self.OnMouseOut )self.addEventHandler( 'keyboard', name='<up>', state=1, modifiers=(0,0,0), function=self.forward )self.addEventHandler( 'keypress', name='-', modifiers=(0,0,0), function=self.straighten)self.addEventHandler( 'mousebutton', button=1, state = 1, modifiers=(0,0,0), function=self.startExamineMode)self.addEventHandler( 'mousemove', buttons=(), modifiers=(0,0,0), function=self.RefreshTooltip)

Callbacks are held weakly — you must keep them alive
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

PyDispatcher holds each registered callback by **weak** reference, and
OpenGLContext relies on that: it is what lets a node or a context be garbage
collected without first unbinding every handler it registered.

The consequence is that **the caller owns the callback**. A function with no
other reference to it is collected as soon as ``addEventHandler`` returns, and
the binding then does nothing at all — the key or button is silently dead,
with no error raised at registration or at dispatch. This is the usual
explanation for “my handler never fires and nothing is logged”.

Pass something that outlives the binding. A bound method of a live object is
the normal choice, and is what every example above uses. A bare closure, a
``lambda``, a ``functools.partial`` or any other object created purely for the
call will *not* survive it; if you need one, store it on something that lives
as long as the binding should:

.. code-block:: python

   self.handlers = []            # an attribute of a long-lived object
   handler = lambda event: self.step( +1 )
   self.handlers.append( handler )
   self.addEventHandler( 'keyboard', name='w', state=1, function=handler )

A held key always comes back up
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A control that acts for as long as a key is down — a throttle, a steering
input, a movement mode — is written as a pair of ``keyboard`` handlers,
``state=1`` to take the key and ``state=0`` to let go of it, with the
application keeping the set of keys currently held.

The window losing focus is the case that pair has to survive: the platform
stops delivering key transitions to an unfocused window, so the release for a
key that was down when focus went away never arrives from it. OpenGLContext
sends that release itself as focus is lost, one ``state=0`` event per key it
was holding, so the set an application keeps is emptied the same way an
ordinary release empties it. Nothing special has to be written for the case:
what reaches the handler is a release like any other.

Timer objects are also based on the same mechanism (with some significant
extra machinery).
