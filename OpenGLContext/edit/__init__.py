"""Editor machinery: the parts of an editor that are not about one editor.

A track editor, a level editor and a scene inspector all want the same things
of the engine -- a pointer that does a different job in each tool, a point on
the terrain under the cursor, a handle to drag it by -- and none of that is
about tracks, levels or scenes. It lives here so the second editor does not
have to write it again.

Nothing here is needed to *play* a world, so a shipped game imports none of it.
"""
