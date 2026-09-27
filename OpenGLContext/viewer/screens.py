"""The viewer's screens, on the keys that raise them.

A viewer is a program, so it has a menu, a library to open things from, a
settings page and a controls page.  The pages themselves are
:mod:`OpenGLContext.viewer.menu`, :mod:`OpenGLContext.ui.settings` and
:mod:`OpenGLContext.ui.bindings` -- the same settings and bindings screens every
other program here shows.  This is the part that belongs to the *context*: which
key raises which, what happens when one is answered, and what a viewer with
nothing to show does instead of exiting.

The keys are deliberately the ones twig-bb uses, so someone who has used one of
these programs knows the other::

    F1    the library: what there is to open
    F10   settings
    F6    controls
    F2    save a screenshot
    Alt+F the developer overlay (every context has this)

The copyright and licence notices the open file carries are on ``i`` (a
character key, bound in :class:`~OpenGLContext.viewer.sceneviewer.SceneViewerMixin`),
and on the menu and each view's menu when the file states any.

They are bound as **key-down** rather than as characters: a function key
produces no character, so a ``keypress`` binding would be accepted and then
never fire.
"""
from typing import TYPE_CHECKING, Any, Optional

from OpenGLContext.loaders.notices import notices_text
from OpenGLContext.viewer import menu

__all__ = ['ViewerScreensMixin', 'NOTICES_NAME']

#: The name the notices screen is pushed under.
NOTICES_NAME = 'viewer-notices'


class ViewerScreensMixin(object):
    """Gives a viewer its menu, its library and the keys that raise them.

    Needs the viewer's own ``viewerLibrary`` and ``openEntry`` beside it; the
    panel stack is the context's own.
    """

    #: Keys the screens are on.  '' binds none, for an application that wants
    #: the key for something else or is driving the screens itself.
    LIBRARY_KEY = '<F1>'
    SETTINGS_KEY = '<F10>'
    BINDINGS_KEY = '<F6>'

    if TYPE_CHECKING:
        overlays: Any
        source: Optional[str]
        scene: Any

        def addEventHandler(self, eventType: str, *arguments: Any,
                            **named: Any) -> Any: ...
        def pushOverlay(self, panel: Any) -> Any: ...
        def viewerLibrary(self) -> Any: ...
        def openEntry(self, entry: Any) -> bool: ...
        def openSource(self, source: str) -> bool: ...
        def OnQuit(self, event: Any = None) -> Any: ...

    # -- setting up --------------------------------------------------------
    def setupScreens(self) -> None:
        """Bind the keys, and open the menu if there is nothing to show yet.

        A viewer started with no source is not an error and not a usage
        message: it is a viewer with its shelf open.
        """
        for key, handler in ((self.LIBRARY_KEY, self.showLibrary),
                             (self.SETTINGS_KEY, self.showSettings),
                             (self.BINDINGS_KEY, self.showBindings)):
            if key:
                self.addEventHandler('keyboard', name=key, state=1,
                                     function=handler)
        if not self.hasSceneToShow():
            self.showMenu()

    def hasSceneToShow(self) -> bool:
        """Whether this viewer has something to open, or is starting empty.

        Whether a *source* was named, by default.  A host with scenes of its own
        -- a catalogue browser, a generator -- has none and is not empty, so it
        overrides this rather than being handed a launch menu over its own
        content.
        """
        return self.source is not None

    def OnEscape(self, event: Any = None) -> Any:
        """Escape puts the menu up rather than throwing the scene away.

        A viewer with a world loaded and a camera somewhere is a session worth
        something, and a key pressed to back out of *something else* must not be
        what ends it.  Resume and Quit are both one click away from here.
        """
        return self.showMenu(event)

    # -- the screens -------------------------------------------------------
    def showMenu(self, event: Any = None) -> Any:
        """Raise the launch menu, or bring up the one already showing."""
        existing = self.overlays.named(menu.MENU_NAME)
        if existing is not None:
            return existing
        # Resume, and Escape, only when there is something behind it to go
        # back to.
        showing = self.hasSceneToShow()
        return self.pushOverlay(menu.main_menu(
            on_browse=self.showLibrary,
            on_settings=self.showSettings,
            on_bindings=self.showBindings,
            on_quit=self.OnQuit,
            on_resume=self.closeMenu if showing else None,
            on_open=self.openTyped,
            on_notices=self.showNotices if self.sceneNotices() else None,
            subtitle=self.menuSubtitle()))

    def openTyped(self, source: str) -> None:
        """Open an address typed into the menu, and get out of its way.

        The menu stays up if it could not be opened, so there is somewhere to
        correct the typo rather than an empty window and a line on stderr.
        """
        if self.openSource(source):
            self.closeMenu()

    def menuSubtitle(self) -> str:
        """What the menu says under its title: how much there is to open."""
        library = self.viewerLibrary()
        return "%d models and worlds on the shelf" % len(library.entries)

    def closeMenu(self, event: Any = None) -> None:
        """Put the menu away, leaving whatever is behind it showing."""
        panel = self.overlays.named(menu.MENU_NAME)
        if panel is not None and not panel.closed:
            panel.close(True)

    def showLibrary(self, event: Any = None) -> Any:
        """Raise the shelf: everything this viewer can offer to open.

        The pictures are filled in here rather than when the shelf was built,
        because finding them means fetching a catalogue and a viewer that never
        opens the library should never pay for it.
        """
        existing = self.overlays.named(menu.BROWSE_NAME)
        if existing is not None:
            return existing
        # Replace the menu rather than covering it: two modal panels means the
        # one underneath showing through the gaps in the one on top.
        self.closeMenu()
        library = self.viewerLibrary().withPreviews()
        return self.pushOverlay(menu.browse_screen(
            library, on_open=self.chooseEntry, on_cancel=self.leaveLibrary))

    def chooseEntry(self, entry: Any) -> None:
        """Open what was chosen, and put the screen away to show it."""
        panel = self.overlays.named(menu.BROWSE_NAME)
        if panel is not None and not panel.closed:
            panel.close(True)
        self.openEntry(entry)

    def leaveLibrary(self, event: Any = None) -> None:
        """Cancelled: back to the menu if that is where this came from.

        A viewer with a scene up goes back to the scene; one with nothing to go
        back to gets the menu again rather than an empty window.
        """
        panel = self.overlays.named(menu.BROWSE_NAME)
        if panel is not None and not panel.closed:
            panel.close(False)
        if not self.hasSceneToShow():
            self.showMenu()      # there is nothing behind it to go back to

    def showSettings(self, event: Any = None) -> Any:
        """Raise the shared settings screen."""
        from OpenGLContext.ui import settings
        return settings.open_settings(self)

    def showBindings(self, event: Any = None) -> Any:
        """Raise the shared key-bindings screen."""
        from OpenGLContext.ui import bindings
        return bindings.open_bindings(self)

    # -- the file's notices ------------------------------------------------
    def sceneNotices(self) -> list:
        """The notices the scene on show carries; empty with none on show.

        A scene built by a third-party adapter may not answer ``notices`` at
        all, which is the same as answering none.
        """
        return list(getattr(getattr(self, 'scene', None), 'notices', None) or [])

    def showNotices(self, event: Any = None) -> Any:
        """Raise the open file's copyright and licence notices.

        Replaces the menu when it came from there, as the library does.  With
        no scene on show there is no file to ask, and nothing goes up.
        """
        if getattr(self, 'scene', None) is None:
            return None
        existing = self.overlays.named(NOTICES_NAME)
        if existing is not None:
            return existing
        self.closeMenu()
        from OpenGLContext.ui.dialogs import notice
        panel = notice(menu.NOTICES_LABEL, notices_text(self.sceneNotices()))
        panel.name = NOTICES_NAME
        return self.pushOverlay(panel)

    def viewMenuItems(self, view: Any) -> list:
        """Each view's menu, with the file's notices at its foot when it has any."""
        above = getattr(super(), 'viewMenuItems', None)
        items = list(above(view)) if above is not None else []
        if self.sceneNotices():
            from OpenGLContext.ui.menu import MenuItem
            items.append(MenuItem(text=menu.NOTICES_LABEL,
                                  on_activate=lambda widget: self.showNotices()))
        return items
