"""What a frozen application needs from the engine beyond its import statements

Three sets of things the engine reaches by name rather than by importing:

* the plug-in registries (:mod:`OpenGLContext.plugins`) -- the windowing
  backends, the format loaders, the viewer's adapters and every scenegraph node,
  each declared as a string and imported when a scene asks for it,
* the generated resource and font-atlas modules, loaded by name from a
  ``res://`` URL and from the size a piece of text is drawn at, and
* the files the engine opens by path: the GLSL sources the render passes are
  built from, and the environment maps a default background is lit by.

Each is reported from the source the running engine uses, so a node or a shader
added to the engine reaches a frozen application without an edit here.

The whole registry is reported, PyOpenGL's own entries included: an application
built on the engine imports both, and naming a module twice costs nothing.
Modules for a toolkit that is not installed are reported too and end up as
missing-import notes in the build log rather than as failures -- the backend
reports itself unavailable at run time, which is what a bundle wants. To leave
an unwanted toolkit out altogether, pass
:func:`OpenGLContext.packaging.unused_backend_modules` to ``excludes``.
"""

from PyInstaller import isolated
from PyInstaller.utils.hooks import collect_data_files, collect_submodules


@isolated.decorate
def _plugin_modules():
    """Modules the plug-in registries would import, the engine's own included"""
    import OpenGLContext  # noqa: F401 -- imported for its registrations
    from OpenGL import plugins

    return plugins.registered_modules()


hiddenimports = (
    _plugin_modules()
    # `res://` URLs and the text renderer name these modules at run time; they
    # are generated Python holding the bytes of an icon, a shader or a font
    # atlas, so they travel as code rather than as data files.
    + collect_submodules('OpenGLContext.resources')
    + collect_submodules('OpenGLContext.scenegraph.text.fonts')
)

# The shaders, the environment maps and the atlas images beside their generated
# modules: everything in the package that is not Python. It is under half a
# megabyte all together, so it is collected wholesale rather than by a list of
# patterns that would go stale as passes are added.
datas = collect_data_files('OpenGLContext')
