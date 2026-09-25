Loading content you did not write
=================================

.. rst-class:: introduction

An application built on this engine opens files that other people wrote: a
model a player chose, a world a server sent, a texture from a marketplace.
Everything inside such a file is a *claim* the file makes: a path, a URL, a
length, a pixel count. This page describes what the engine does with those
claims, so you know what the engine protects against and what your
application has to decide itself.

.. _core:

The resolver
------------

``OpenGLContext.loaders.resolver`` defines the rules. Every loader that
follows a reference from a document goes through it, so there is one set of
rules to check rather than one per loader. It is a public API: a loader in
another package, or one you write for a new format, applies the same rules by
importing the same names.

.. code-block:: python

   from OpenGLContext.loaders.resolver import Resolver

   resolver = Resolver(base_dir='/where/the/document/is')   # or base_url=...
   path = resolver.resolve(uri_from_the_document)           # policy, no I/O
   data = resolver.fetch(uri_from_the_document)             # policy, then bytes

.. list-table::
   :widths: auto
   :header-rows: 1

   * - What a document does
     - What the resolver enforces
   * - References a file beside it
     - The reference must resolve under the document's own directory. An absolute
       path, a ``../`` climb, a percent-encoded climb and a URL scheme are all
       refused. The check uses the *real path*, so a symbolic link out of the
       directory is refused too.
   * - References a URL, having been loaded from a URL
     - The reference must have the same origin: scheme, host and port. Every
       redirect is checked again, so a ``302`` redirect to ``169.254.169.254`` is
       refused just as a direct request to it would be.
   * - Is large
     - Every fetched or decoded resource is size-capped (``max_resource_bytes``,
       256 MiB by default). A local file's size is checked on disk before it is
       read, so a large file beside the document is refused without being read
       into memory.
   * - Carries its own bytes
     - A ``data:`` URI is decoded under the same cap.
   * - Is fetched more than once
     - Remote resources are cached on disk under the per-user app-data directory,
       not in a system temporary directory that every account can write to, so
       another account cannot plant a cache entry that this user then loads.

.. _answers:

A URL returned by a service
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Some loaders ask an online catalogue, such as ambientCG or Poly Haven, where
an asset is, and the service replies with a link. Treat that reply as
untrusted data too. A compromised, misconfigured or faulty service can reply
with a local address, an unencrypted ``http`` link, or a ``file://`` path.
Check the link with ``resolver.require_host(url, hosts)``, where ``hosts`` are
the host names the provider serves files from. List them in your code in
advance: they are a fact about the provider, not about the reply.
``require_host`` requires ``https`` and compares the parsed host name exactly.
It refuses a host that only *ends* in an allowed name, a host hidden in the
user-info part of the URL, and a non-default port.

A service's link may answer with a redirect. Open it with
``resolver.open_url(url, redirects=resolver.AllowedHosts(hosts))`` so that
every hop is given the same test before it is followed; ``urllib`` on its own
follows a redirect to any host.

.. _loaders:

Rules for each loader
---------------------

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Loader
     - How its references are restricted
   * - :doc:`glTF / GLB <gltf>` (``loaders/gltf/``)
     - Buffers, images and audio resolve through a ``Resolver`` built from the
       document's own location. ``MSFT_lod``'s coarser levels are ordinary glTF
       buffers and follow the same rules.
   * - :doc:`VRML97 <vrml97>` (``loaders/vrml97.py``) and every ``url`` field
     - ``loaders.loader.Loader`` resolves each reference against the document's
       ``baseURI`` through the ``Resolver``. The *top-level* document a user chose
       is not restricted in where it comes from, because the user asked for it,
       but it is still size-capped.
   * - Wavefront OBJ (``loaders/obj.py``)
     - ``mtllib`` and texture references go through the same ``Loader``, so they
       are restricted to the model's directory.
   * - :doc:`3D Tiles <tiles3d>` (``loaders/tiles3d/``)
     - Tile content and nested tilesets resolve through the ``Resolver``, with a
       separate cap for each tile. The files a world names in its extras
       (terrain maps, trees, ground cover, zones) are held to the same rules by
       ``tiles3d.fetch.beside``. See :ref:`What a tileset may reach
       <tiles3d-reach>`.
   * - ambientCG materials (``loaders/cc0.py``)
     - The service's reply is size-capped, the download link is checked against
       the hosts ambientCG serves files from, the archive is size-capped, and each
       member's declared size is checked *before* it is written. Texture maps are
       written to paths the loader chooses, never to a name taken from the archive.
   * - :doc:`Content packs <contentpacks>` (``contentpacks/``)
     - The download is size-capped, its ``sha256`` is checked against the registry,
       and extraction is limited by an unpacked size. Every member name, in a tar or
       a zip, is refused if it is absolute or would be written outside the pack's
       directory. A tar is also extracted with ``filter='data'``, which refuses
       links that point out of the directory, device files, and permission bits
       the archive sets. See :ref:`Size limits <bombs>`.
   * - Baked LOD chains (``OpenGLContext_editor.meshlod``)
     - A level's sidecar file must be in the directory of its ``.glb``, and the
       number of bytes an accessor may request is limited. The engine reads a chain
       through the glTF loader above.

.. _asks:

What a glTF file may ask the engine to do
-----------------------------------------

Beyond geometry and materials, a glTF file can ask the engine for behaviour
through three extensions. Each selects among things the running program
provides; none names code, a module or a command.

.. list-table::
   :widths: auto
   :header-rows: 1

   * - Extension
     - What a file can ask for, and the limits on it
   * - :ref:`OGLC_hook <hooks>`
     - A kind from the registry: whatever the application registered, and the
       engine's own ``water``, ``mirror``, ``fire``, ``smoke`` and ``sparks``.
       A ``water`` surface moves and bounds a volume; its ``depth`` is at least
       0 and its ``medium`` one the engine has. A ``mirror`` is drawn within
       the frame's :doc:`reflection budget <reflections>`, at a ``scale`` from
       0.05 to 1 of its rectangle on screen. A ``fire``, ``smoke`` or
       ``sparks`` emitter holds at most 20000 particles and emits at most 2000
       a second, and a ``texture`` it names is resolved through the
       ``Resolver``, so it is read only from inside the directory of a
       document loaded from a file. ``externalURL`` cannot be set.
   * - :doc:`OGLC_zone <extensions/OGLC_zone>`
     - A region of space whose lighting, sound, reverb, visibility, mirrors
       and gravity differ inside it. Each extension inside a zone is read by a
       reader the program registered. A zone that captures its own environment
       probe renders the scene into a cube map; the engine captures at most
       one zone a frame.
   * - ``EXT_lights_image_based``
     - Environment lighting shipped as images. The images are read through
       the ``Resolver`` like any other, and decoded under :ref:`Pillow's
       pixel limit <images>`, and only for a light a scene or a zone names.
       A light with an image that cannot be read, faces that are not square
       and alike with each mip half the one before, or coefficients that are
       not nine rows of three numbers, is left out.

Every value these extensions read is checked before it is used
(``loaders.documentvalues.DocumentValues``). A value that is not a finite
number of the right kind is logged once for the document and replaced by its
default, and a value outside its range is logged and taken as the nearer end
of it. A hook that raises is logged, and the material or node that carried it
loads as an ordinary one. None of these ends a load.

The number of tagged objects and zones in a file is not limited: a file with
a thousand ``fire`` objects makes a thousand emitters. Setting
``OPENGLCONTEXT_GLTF_HOOKS=0`` leaves every ``OGLC_hook`` tag in every file
unread, which an application that shows models from sources it does not trust,
and has no use for the tags, can set for its process.

.. _images:

Images
------

An image file states its size in a header, and a decoder allocates memory from
that size before reading any pixels. A sixty-six-byte file can ask for forty
gigabytes. Pillow refuses such images for the formats it decodes. The engine's
own Radiance HDR decoder calls ``resolver.check_pixels``, which uses Pillow's
pixel limit, so both decoders apply the same limit.

A texture that fails to decode, for this or any other reason, affects only
that texture, not the scene. The failure is logged and the node is left
without an image. If the node's ``url`` field lists alternatives, the next one
is tried.

.. _yours:

What your application decides
-----------------------------

The engine limits what a document can reach and how much data can arrive. The
following depend on what you are building, so your application decides them:

- Whether to open the file at all. The engine fetches the top-level document a
  user names. If your application accepts a URL from a source less trusted
  than its own user, check the URL before passing it to the loader.

- How much is too much. The caps are defaults. If your application has its own
  memory budget, pass ``max_resource_bytes``. A server-side renderer should set
  it much lower than a desktop viewer.

- Time. A document can be built so that parsing it is slow even though it is
  small. The engine does not limit how long a load takes.

- The licence. Whether content may be opened, redistributed or baked into
  something else depends on its licence, not its format; see :ref:`Licensing
  <licensing>` in Content packs.

A way past any of the engine's limits above is a defect in the engine. Please
report it on the `issue tracker
<https://github.com/mcfletch/openglcontext/issues>`__.
