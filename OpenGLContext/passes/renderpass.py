"""Choosing the rendering pass for a context.

One decision lives here: which :class:`~OpenGLContext.passes._flat.FlatPass`
subclass renders a given context, given its profile and the renderer it asked
for, and the caching of that pass across frames.

The pass itself does the work -- ``_flat.FlatPass`` observes the scenegraph's
structure and renders from the paths it knows are active. This module only picks
one and hands the context to it.
"""
from OpenGLContext.passes import viewpointbinding
import logging
log = logging.getLogger( __name__ )


USE_FLAT = True
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


class _defaultRenderPasses( object ):
    def __call__( self,context ):
        global FLAT
        sg = context.getSceneGraph()
        # Rebuild when the scenegraph reference itself changes — wholesale
        # replacement (self.sg = new_sg) doesn't fire the per-child dispatcher
        # signals SGObserver listens to, so the cached FlatPass would keep
        # rendering the old tree.
        if FLAT is None or FLAT.scene is not sg:
            # Free the outgoing pass's GPU-side shadow maps before dropping it.
            # We're inside OnDraw with the context current, so this is the safe
            # point to delete those FBOs/textures rather than leak them when the
            # cached pass is replaced on a scenegraph swap.
            if FLAT is not None and hasattr(FLAT, 'disposeShadowMaps'):
                try:
                    FLAT.disposeShadowMaps()
                except Exception as err:
                    log.debug("shadow map disposal on pass swap failed: %s", err)
            if context.contextDefinition.profile == 'core':
                FlatPass = _core_flatpass_class()
            else:
                log.info( 'Using compatibility profile' )
                from OpenGLContext.passes.flatcompat import FlatPass
            FLAT = FlatPass( sg, context.allContexts )
            if sg is None:
                FLAT.integrate( context.renderedChildren()[0] )
        if context.contextDefinition.profile == 'core':
            # The core FlatPass takes its camera from the view platform only, so
            # bind the scene's active Viewpoint into the platform here (the legacy
            # path does this inside its scenegraph traversal instead).
            viewpointbinding.bind_scene_viewpoint( context )
        return FLAT( context )
defaultRenderPasses = _defaultRenderPasses()
