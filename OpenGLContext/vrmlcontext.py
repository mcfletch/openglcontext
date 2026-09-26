"""Scene loading and fonts, for a Context that shows a loaded world

:class:`VRMLSceneMixin` is one of :class:`~OpenGLContext.context.Context`'s
bases: :meth:`~VRMLSceneMixin.load` replaces the scene with one read from a
file or URL, in any format the loader registry knows (VRML97, glTF, OBJ), and
:meth:`~VRMLSceneMixin.ensureFontProviders` loads the font providers ``Text``
nodes draw with, the first time one is drawn.
"""

from typing import TYPE_CHECKING, Any

from OpenGLContext.loaders.loader import Loader
import logging

log = logging.getLogger(__name__)

if TYPE_CHECKING:
    class _Host:
        """What this mix-in needs of the class beside it.

        Declared for a checker and aliased to ``object`` at run time, so the
        MRO is exactly what the concrete context's bases make it:
        :class:`~OpenGLContext.context.Context` is what really provides these,
        and naming it as a base here would put a second copy in that order.
        """

        def getTTFFiles(self) -> Any: ...
else:
    _Host = object


class VRMLSceneMixin(_Host):
    """Scene loading and font providers for a context showing a world

    Attributes:
        initialPosition -- where the camera starts, before the scene binds a
            viewpoint of its own
        sg -- the scenegraph :meth:`load` read, or None
    """

    initialPosition = (0, 0, 10)
    USE_FRUSTUM_CULLING = 1
    USE_OCCLUSION_CULLING = 0
    sg: Any = None
    #: Set once :meth:`setupFontProviders` has run.
    fontProvidersReady = False

    def ensureFontProviders(self) -> None:
        """Load the font providers, once, before the first text is drawn.

        Deferred until something draws text, because loading them scans the
        system's fonts and imports FontTools, which a context that draws no
        text has no use for.  ``Text`` calls this as it compiles.
        """
        if not self.fontProvidersReady:
            self.fontProvidersReady = True
            self.setupFontProviders()

    def setupFontProviders(self) -> None:
        """Load font providers for the context

        See the OpenGLContext.scenegraph.text package for the
        available font providers.  Called by :meth:`ensureFontProviders`;
        a context that offers other fonts overrides this.
        """
        from OpenGLContext.scenegraph.text import fontprovider

        try:
            from OpenGLContext.scenegraph.text import toolsfont

            registry = self.getTTFFiles()
        except ImportError:
            log.warning(
                """Unable to import TTFQuery/FontTools-based TTF-file registry, no TTF font support!"""
            )
        else:
            fontprovider.setTTFRegistry(
                registry,
            )
        try:
            from OpenGLContext.scenegraph.text import pygamefont
        except (ImportError, NotImplementedError):
            log.warning(
                """Unable to import PyGame TTF-font renderer, no PyGame anti-aliased font support!"""
            )
        try:
            from OpenGLContext.scenegraph.text import glutfont
        except ImportError:
            log.error(
                """Unable to import GLUT-based font renderer, no GLUT bitmap font support (this is unexpected)!"""
            )

    def load(self, filename: str) -> None:
        """Load given url, replacing current scenegraph"""
        self.sg = Loader.load(filename)


#: The mix-in, under the name it is also published as.  The ``*vrmlcontext``
#: modules of each window system export :class:`~OpenGLContext.context.Context`
#: with that window system chosen, under this same name.
VRMLContext = VRMLSceneMixin
