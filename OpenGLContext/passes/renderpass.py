"""Choosing the rendering pass for a context.

One decision lives here: which :class:`~OpenGLContext.passes._flat.FlatPass`
subclass renders a given context, given its profile and the renderer it asked
for, and the caching of that pass across frames.

The pass itself does the work -- ``_flat.FlatPass`` observes the scenegraph's
structure and renders from the paths it knows are active. This module only picks
one and hands the context to it.
"""
from typing import Any, Dict

from OpenGLContext import contextresources
from OpenGLContext.passes import viewpointbinding
import logging
log = logging.getLogger( __name__ )


USE_FLAT = True

#: One pass per GL context.  A pass holds GL object *names* -- programs,
#: buffers, shadow-map textures -- which the context that issued them is the
#: only place they mean anything; handing them to a second context draws
#: through names its driver never issued.
#:
#: A mapping rather than one slot, because a program holding two windows draws
#: both of them.  With one slot each frame of each context displaces the other's
#: pass and rebuilds its own, and the displaced pass is dropped still holding
#: shadow maps in a context that is alive -- which nothing can then be told to
#: delete, since deleting them needs that context current.
#: ``shaderpass.get_shader_program`` is keyed the same way, for the same reason.
_passes: Dict[Any, Any] = {}

#: The pass that rendered most recently, whatever context that was in.  For the
#: demos that toggle ``use_shaders`` on it and for :func:`report_render_failures`;
#: :data:`_passes` is what dispatch reads.
FLAT = None


def report_render_failures() -> None:
    """Say what the session rendered from and could not draw.

    A pass catches each node's exceptions so one bad node cannot take the frame
    with it, which leaves a scene able to draw nothing while the process exits
    successfully.  Called as a context quits, this is the line that names the
    nodes behind an otherwise silent black window.
    """
    if FLAT is not None:
        FLAT.reportFailures()


def _core_flatpass_class():
    """Core-profile pass class, guarding the experimental PBR import.

    The dispatcher must not name ``pbrpass`` unconditionally: an import-time fault
    anywhere in the PBR chain (pbrpass -> pbrmaterial/transmission/ibl/flatcore)
    would otherwise break plain core rendering for every user, PBR or not. The PBR
    path is attempted defensively and falls back to the base core ``FlatPass``.
    """
    want_pbr = False
    try:
        from OpenGLContext.passes.pbrpass import renderer_is_pbr
        want_pbr = renderer_is_pbr()
    except Exception as err:
        log.warning("PBR renderer detection failed (%s); using plain core", err)
    if want_pbr:
        try:
            from OpenGLContext.passes.pbrpass import PBRPass
            log.info('Using core profile (PBR renderer)')
            return PBRPass
        except Exception as err:
            log.warning("PBR pass unavailable (%s); using plain core", err)
    else:
        log.info('Using core profile')
    from OpenGLContext.passes.flatcore import FlatPass
    return FlatPass


def _dispose( pass_, why ):
    """Delete a pass's GPU-side shadow maps.

    Only ever called with the pass's own context current, which is what makes
    deleting the names legitimate: an FBO name means something else in another
    context, and deleting it there takes that context's object instead.
    """
    if hasattr( pass_, 'disposeShadowMaps' ):
        try:
            pass_.disposeShadowMaps()
        except Exception as err:
            log.debug( "shadow map disposal on %s failed: %s", why, err )


def cached_pass( scene, build ):
    """The pass for the context that is current, built by ``build`` if there is
    not one for it yet.

    Rebuilt when the scenegraph reference itself changes: wholesale replacement
    (``self.sg = new_sg``) does not fire the per-child dispatcher signals
    SGObserver listens to, so the cached pass would keep rendering the old tree.
    Not rebuilt when another context drew in between, which is the whole point
    of keying on the context.
    """
    global FLAT
    key = contextresources.context_key()
    existing = _passes.get( key )
    if existing is not None and existing.scene is scene:
        FLAT = existing
        return existing
    if existing is not None:
        # Replacing this context's own pass, with this context current, so its
        # shadow maps can go rather than be leaked.
        _dispose( existing, 'pass swap' )
    FLAT = _passes[key] = build()
    return FLAT


class _defaultRenderPasses( object ):
    def __call__( self,context ):
        sg = context.getSceneGraph()

        def build():
            if context.contextDefinition.profile == 'core':
                FlatPass = _core_flatpass_class()
            else:
                log.info( 'Using compatibility profile' )
                from OpenGLContext.passes.flatcompat import FlatPass
            built = FlatPass( sg, context.allContexts )
            if sg is None:
                built.integrate( context.renderedChildren()[0] )
            return built

        pass_ = cached_pass( sg, build )
        if context.contextDefinition.profile == 'core':
            # The core FlatPass takes its camera from the view platform only, so
            # bind the scene's active Viewpoint into the platform here (the legacy
            # path does this inside its scenegraph traversal instead).
            viewpointbinding.bind_scene_viewpoint( context )
        return pass_( context )
defaultRenderPasses = _defaultRenderPasses()


@contextresources.on_context_lost
def drop_pass() -> None:
    """Let go of this context's pass as the context dies.

    The context is still current here, so its shadow maps can be deleted rather
    than leaked; the pass itself goes because every other GL name it holds --
    programs, buffers, textures -- dies with the context, and the next window
    the driver hands the same address must not be given them to draw through.

    Only this context's.  Another window's pass is another window's, and it is
    still drawing.
    """
    global FLAT
    key = contextresources.context_key()
    dying = _passes.pop( key, None )
    if dying is None:
        return
    _dispose( dying, 'context loss' )
    if FLAT is dying:
        FLAT = None
