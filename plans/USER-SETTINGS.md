# Plan: user settings against game settings

**Status:** 🔶 Partly built — the callback and the change-set exist; the split
itself is designed but not implemented.

## The problem

`ContextDefinition` is one node holding two kinds of thing that behave nothing
alike.

* **What the game shipped.** Window title, GL profile, buffer format, which
  movement modes exist, what the developer decided the world needs. It is
  authored with the game, distributed with it, and a later build should be free
  to change it. A player must not be able to edit it in-game, and an editor for
  it is a *developer* tool.
* **What the player chose.** Shadows off because the machine is slow, interface
  size up because the display is 4K, mouse sensitivity, key bindings. It is
  edited live, has to survive a restart, and must **not** be overwritten by a
  new build's defaults.

Today the settings screen edits the one node and the two are indistinguishable
once written. Saving the whole node to disk would freeze every default the game
ships, so that the next build's improved default never reaches a player who once
opened the settings screen. Saving nothing loses the player's choices at exit.

## What is built

`settings.settings_panel(context, on_apply=...)` and
`settings.open_settings(context, on_apply=...)` call back once the draft has
been committed into the live definition, and hand over the session. That is
where a game decides what the changes mean — writing a file, sending them to a
server, or nothing.

`SettingsSession.changed_fields()` answers **which fields the user actually
moved**, measured against the values the screen opened with rather than against
the target, so it is still right after the commit. Persisting only those keeps a
player's choices without freezing the rest:

```python
def saveSettings(session):
    changed = session.changed_fields()
    profile.write({name: getattr(session.draft, name) for name in changed})

settings.open_settings(context, on_apply=saveSettings)
```

That is enough for a game to persist settings correctly today. What it does not
give is a way to *stop* a player editing something, or a way to load a saved
profile back over a definition at start-up without hand-writing the loop.

## What is left

### 1. A field says which kind it is

A `UI_HINTS` entry per field, beside the field, the way every other presentation
decision is already declared:

```python
UI_HINTS = {
    'shadows':  {'label': 'Shadows', 'audience': 'player'},
    'profile':  {'label': 'OpenGL profile', 'audience': 'developer',
                 'restart': True},
}
```

`player` is the sensible default for a field that has a hint at all; `developer`
means the settings screen shows it read-only, or not at all, and a developer
tool shows it as an editor. The alternative — two node classes — was rejected:
it splits `ContextDefinition` in a way every existing caller would have to learn,
and the distinction is genuinely per field rather than per record.

### 2. Persistence that is not the caller's problem

A `usersettings` module beside `move.bindingstore`, which already solves exactly
this problem for key bindings and should be followed rather than reinvented:

* `load_user_settings(definition)` at start-up, applied **over** the shipped
  definition, so an unsaved field keeps whatever the build now defaults to.
* `save_user_settings(session)` from `on_apply`, writing only
  `changed_fields()` filtered to the `player` audience.
* JSON in the per-user app-data directory, and **forgiving on load**: a file
  naming a field this build no longer has keeps the entries that still resolve,
  exactly as `bindingstore` does.

The environment variable stays the *default* underneath both, as it is today
(see `OpenGLContext.renderoptions`), giving a clean precedence: environment,
then what the game shipped, then what the player saved.

### 3. A developer editor

The same generated page over the `developer` fields, opened from a separate key
and not offered in a shipped build. `generate.page_for` already takes an
`include` list, so this is an authoring decision rather than new machinery.

## Notes

* Key bindings are already on the right side of this line: they are the player's,
  they are saved separately by `move.bindingstore`, and the settings screen's
  Cancel deliberately does not undo them.
* `TRANSIENT_FIELDS` is a third category that already exists and is unaffected:
  fields that are *published* rather than chosen (`movementMode`), which no
  session carries and nothing saves.
