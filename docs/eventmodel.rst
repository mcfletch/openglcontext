OpenGLContext Event Model
=========================

.. rst-class:: introduction

The event model is how OpenGLContext makes a scene interactive. It covers
keyboard and mouse input, timers, the watching of node fields, cache
invalidation and VRML97 routes.

Parts of the event model
------------------------

- Field watching - code registers a callback for changes to a given field of
  a given node.
- Cache invalidation - built on field watching. A cached value is discarded
  when a field it was computed from changes.
- Routing - VRML97 ``ROUTE`` statements and ``PROTO`` ``IS`` mappings link
  fields, so that setting one field updates the fields linked to it.
- Event handlers - code registers callbacks for keyboard, mouse and timer
  events. Mouse handlers can also be registered on individual nodes, so an
  interactive object carries its own handlers.

Each of these is described below.

The dispatcher
--------------

All of these are built on the PyDispatcher package. A callback is registered
for a signal from a sender, and is called whenever that sender sends that
signal. Each field of each node sends a signal when its value is set or
deleted. Each event manager registers the callbacks for its event type with
the dispatcher, and sends each event through the dispatcher when it arrives.

Field watching
--------------

A field sends a signal when its value is set or deleted. Fields set while the
VRML97 parser builds a scene send no signal, except on prototyped nodes.
Application code rarely watches fields directly; cache invalidation and
routing are built on it.

Cache invalidation
------------------

A node that caches derived data registers a dependency on each
``(node, field)`` pair the data was computed from. When that field sends its
change signal, the cache entry is discarded, and the node computes its data
again on the next rendering pass.

Routing
-------

There are two kinds of routing:

- A ``ROUTE`` is a one-way channel from a field of one node to a field of
  another. Setting the source field sets the destination field. A scene can
  link its nodes this way, and code that changes one field does not have to
  find and update the fields that depend on it.
- A ``PROTO``'s ``IS`` mapping links a prototype node's fields to fields of
  nodes inside the prototype's own scenegraph. The link works in both
  directions: setting the prototype's field updates the internal node, and
  setting the internal node's field updates the prototype's field.

.. _event-handlers:

Event handlers
--------------

Most contexts derive from ``EventHandlerMixin``, which provides
``addEventHandler``. It registers a callback for one event type, named by a
string, and the keyword arguments say which events of that type the callback
receives. Each event type has its own event manager, which uses PyDispatcher
to keep its table of callbacks.

.. code-block:: python

   self.addEventHandler("mousein", function=self.OnMouseIn)
   self.addEventHandler("mouseout", function=self.OnMouseOut)
   self.addEventHandler('keyboard', name='<up>', state=1,
                        modifiers=(0, 0, 0), function=self.forward)
   self.addEventHandler('keypress', name='-', modifiers=(0, 0, 0),
                        function=self.straighten)
   self.addEventHandler('mousebutton', button=1, state=1,
                        modifiers=(0, 0, 0), function=self.startExamineMode)
   self.addEventHandler('mousemove', buttons=(), modifiers=(0, 0, 0),
                        function=self.RefreshTooltip)

``keyboard`` events are key transitions: ``state=1`` is a press and
``state=0`` a release. ``keypress`` events are character input. A function
key produces no character, so bind it on ``keyboard`` (see
:ref:`overlayui-quickstart`). Passing ``function=None`` removes a handler and
returns the one it replaces.

Mouse events reach handlers after the selection pass has resolved what is
under the pointer; :ref:`events-and-selection` describes that path, and
:doc:`multiview` describes how an event is routed to one of several views.
For held-key movement, the movement modes read an input sampler rather than
single events; see :ref:`navigation-input`.

Keep each callback alive
~~~~~~~~~~~~~~~~~~~~~~~~

PyDispatcher holds each registered callback by **weak** reference. This lets
a node or a context be garbage collected without first unbinding every
handler it registered.

The caller must keep the callback alive. A function with no other reference
to it is collected as soon as ``addEventHandler`` returns. The binding then
does nothing, and no error is raised at registration or at dispatch. A handler
that never runs and logs nothing usually has this cause.

A bound method of a live object is the usual choice, and the examples above
all use one. A closure, a ``lambda`` or a ``functools.partial`` created for
the call is collected when the call returns. To use one, store it on an
object that lives as long as the binding should:

.. code-block:: python

   self.handlers = []            # an attribute of a long-lived object
   handler = lambda event: self.step( +1 )
   self.handlers.append( handler )
   self.addEventHandler( 'keyboard', name='w', state=1, function=handler )

Held keys and focus loss
~~~~~~~~~~~~~~~~~~~~~~~~

A control that acts while a key is down, such as a throttle, steering or a
movement mode, is a pair of ``keyboard`` handlers: ``state=1`` records the
key as held and ``state=0`` removes it. The application keeps the set of held
keys.

A window that loses focus receives no key releases from the platform. When
focus is lost, OpenGLContext sends a ``state=0`` event for each key that was
down (``clearHeldKeys()``). The handler receives an ordinary release, and the
application's set of held keys empties as it does for any other release.

Timers
------

A ``Timer`` (``OpenGLContext.events.timer``) is an event manager for time.
It runs over an internal clock that can be started, stopped, paused, resumed
and run faster or slower. Its event types are ``start``, ``stop``, ``pause``,
``resume``, ``cycle`` and ``fraction``:

.. code-block:: python

   from OpenGLContext.events.timer import Timer

   self.time = Timer(duration=8.0, repeating=1)
   self.time.addEventHandler("fraction", self.OnTimerFraction)
   self.time.register(self)      # attach it to this context's time manager
   self.time.start()

   def OnTimerFraction(self, event):
       self.rotation = event.fraction() * -360

``duration`` is the length of one cycle in seconds, and a ``fraction`` event
carries how far through the cycle the timer is, from 0 to 1.
:doc:`tutorials/nehe6_timer` walks through a complete example.
