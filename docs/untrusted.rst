Loading content you did not write
=================================

.. rst-class:: introduction

A model, a world or a texture is a file somebody else wrote, and an
application built on this engine will open one a player chose, a server sent
or a marketplace published. Everything inside such a file is a *claim*: a
path, a URL, a length, a pixel count. This page says what the engine does with
those claims, so an application can know what it is relying on and where its
own responsibility starts.

.. _core:

One containment core
--------------------

``OpenGLContext.loaders.resolver`` holds the policy, and every loader that
follows a reference goes through it rather than keeping rules of its own — a
containment rule with a second implementation somewhere else is a containment
rule with a hole in it. It is public API: a loader in another distribution, or
one you write for a format this project has never heard of, is held to the
same policy by importing the same names.

.. code-block:: python

   from OpenGLContext.loaders.resolver import Resolver

   resolver = Resolver(base_dir='/where/the/document/is')   # or base_url=...
   path = resolver.resolve(uri_from_the_document)           # policy, no I/O
   data = resolver.fetch(uri_from_the_document)             # policy, then bytes

.. list-table::
   :widths: auto
   :header-rows: 1

   * - What a document may do
     - What is enforced
   * - Reference a file beside it
     - The reference resolves under the document's own directory. An absolute path, a
       ``../`` climb, a percent-encoded climb and a URL scheme are all refused, on
       the *realpath*, so a symlink out is refused too.
   * - Reference a URL, having come from one
     - Same origin only — scheme, host and port — re-checked on every redirect hop,
       so a ``302`` to ``169.254.169.254`` is refused as the first request would have
       been.
   * - Be large
     - Every fetched or decoded resource is size-capped (``max_resource_bytes``,
       256 MiB by default). A local file is measured on disk before it is read, so a
       confined but enormous sibling is refused rather than read into memory and
       measured after.
   * - Carry its own bytes
     - A ``data:`` URI is decoded against the same cap.
   * - Be fetched more than once
     - A remote reference goes through a disk cache under the per-user app-data
       directory, not world-writable system temp, so no other account can pre-seed an
       entry this user then loads.

.. _answers:

A URL that arrived in an answer
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

A catalogue — ambientCG, Poly Haven — is asked where an asset lives and
replies with a link. That reply is data like any other: a service that is
compromised, misconfigured or simply wrong can answer with a local address, a
plaintext link, or a ``file://`` path. ``resolver.require_host(url, hosts)``
is the check, and the hosts are named by the caller in advance because they
are a fact about the provider rather than about the reply. It requires
``https``, compares the parsed host exactly, and refuses a name that merely
*ends* in an allowed one, a host smuggled in userinfo, and a non-default port.

.. _loaders:

What each loader does
---------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Loader
     - How its references are confined
   * - glTF / GLB (``loaders/gltf/``)
     - Buffers, images and audio resolve through the Resolver built from the
       document's own location. ``MSFT_lod``'s coarser levels are ordinary glTF
       buffers and go the same way.
   * - VRML97 (``loaders/vrml97.py``) and every ``url`` field
     - ``loaders.loader.Loader`` resolves a reference against the document's
       ``baseURI`` through the Resolver. The *top-level* document a person chose is
       not confined — it is the thing they asked for — but it is still size-capped.
   * - Wavefront OBJ (``loaders/obj.py``)
     - ``mtllib`` and texture references go through the same ``Loader``, so they are
       confined to the model's directory.
   * - 3D Tiles (``loaders/tiles3d/``)
     - Tile content and nested tilesets resolve through the Resolver, with a per-tile
       byte cap of its own.
   * - ambientCG materials (``loaders/cc0.py``)
     - The API answer is capped, the download link is checked against the hosts
       ambientCG publishes from, the archive is capped, and each member's declared
       size is checked *before* it is written. Maps are written to paths this code
       computes, never to a name out of the archive.
   * - Content packs (``contentpacks/``)
     - Capped download, ``sha256`` checked against the registry, and extraction
       bounded by an unpacked limit. A tar is extracted with ``filter='data'``, which
       refuses an absolute or climbing member; Python's own zip extraction sanitises
       member names the same way.
   * - Baked LOD chains (``OpenGLContext_editor.meshlod``)
     - A level's sidecar must be under the directory the ``glb`` is in, and how many
       bytes an accessor may ask for is bounded. The engine's own reading of a chain
       is the glTF loader above.

.. _images:

Images
------

An image format states its size in a header and a decoder allocates against
that statement before it has read a pixel, so sixty-six bytes can ask for
forty gigabytes. Pillow refuses that arithmetic for the formats it decodes,
and the Radiance HDR decoder written here asks ``resolver.check_pixels`` —
which carries Pillow's own threshold, so a picture is judged the same way
whichever decoder reads it. A texture that cannot be decoded, for that reason
or any other, costs the texture and not the scene: it is logged, the node is
left without an image, and where a ``url`` field lists alternatives the next
one is tried, a file that does not decode having not succeeded.

.. _yours:

What is left to the application
-------------------------------

The engine bounds what a document can reach and how much of it can arrive. It
does not, and cannot, decide the things that depend on what you are building:

- **Whether to open the file at all.** The top-level document a user names is
  fetched as asked. An application that accepts a URL from somewhere less
  trusted than its own user should decide that before handing it over.

- **How much is too much.** The caps are defaults. An application with a memory
  budget of its own passes ``max_resource_bytes``, and a server-side renderer
  should set it far lower than a desktop viewer would.

- **Time.** A document can be shaped so that parsing it is slow without being
  large. Nothing here bounds how long a load takes.

- **The licence.** Whether content may be opened, redistributed or baked into
  something else is a question no format answers; see :doc:`Content packs
  <contentpacks>`.

If you find a way past any of the above, it is a defect in the engine rather
than a matter for the application to work around, and it should be reported as
one.
