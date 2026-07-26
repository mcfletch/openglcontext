"""Editing a node on a copy: what makes Cancel real at every level."""

import pytest
from vrml import field, node

from OpenGLContext.ui.session import SettingsSession


class Walk(node.Node):
    PROTO = 'UITestWalk'
    name = field.newField('name', 'SFString', 1, 'walk')
    speed = field.newField('speed', 'SFFloat', 1, 3.0)
    keys = field.newField('keys', 'MFString', 1, list)


class Settings(node.Node):
    PROTO = 'UITestSettings'
    shadows = field.newField('shadows', 'SFBool', 1, True)
    lights = field.newField('lights', 'SFInt32', 1, 4)
    title = field.newField('title', 'SFString', 1, 'game')
    modes = field.newField('modes', 'MFNode', 1, list)
    walk = field.newField('walk', 'SFNode', 1, node.NULL)


@pytest.fixture
def target():
    return Settings(modes=[Walk(), Walk(name='run', speed=6.0)],
                    walk=Walk(name='swim', speed=2.0))


@pytest.fixture
def session(target):
    return SettingsSession(target)


class TestDraft:
    def test_the_draft_starts_equal_to_the_target(self, session, target):
        assert session.draft.lights == target.lights
        assert session.draft.title == target.title

    def test_the_draft_is_not_the_target(self, session, target):
        assert session.draft is not target

    def test_editing_the_draft_leaves_the_target_alone(self, session, target):
        session.draft.lights = 1
        assert target.lights == 4

    def test_a_fresh_session_is_clean(self, session):
        assert not session.dirty

    def test_an_edit_makes_it_dirty(self, session):
        session.draft.lights = 1
        assert session.dirty

    def test_setting_a_field_back_makes_it_clean_again(self, session):
        session.draft.lights = 1
        session.draft.lights = 4
        assert not session.dirty

    def test_commit_writes_the_edits_through(self, session, target):
        session.draft.lights = 7
        session.commit()
        assert target.lights == 7

    def test_commit_leaves_the_session_clean(self, session):
        session.draft.lights = 7
        session.commit()
        assert not session.dirty

    def test_revert_throws_the_edits_away(self, session, target):
        session.draft.lights = 7
        session.revert()
        assert target.lights == 4
        assert session.draft.lights == 4
        assert not session.dirty

    def test_commit_never_swaps_a_shared_sub_node(self, session, target):
        """A sub-record may be USEd twice; replacing the SFNode would leave the
        second reference pointing at the old one."""
        original = target.walk
        session.draft.walk.speed = 9.0
        session.commit()
        assert target.walk is original
        assert target.walk.speed == 9.0

    def test_watchers_of_a_field_hear_the_commit(self, session, target):
        seen = []
        from vrml import protofunctions
        receiver = lambda *args, **named: seen.append(args)   # noqa: E731
        protofunctions.getField(target, 'lights').watch(target, receiver)
        target._test_receiver = receiver     # dispatcher holds receivers weakly
        session.draft.lights = 2
        session.commit()
        assert seen, "committing did not notify the field's watchers"

    def test_a_list_of_sub_nodes_is_copied_not_shared(self, session, target):
        assert session.draft.modes[0] is not target.modes[0]
        session.draft.modes[0].speed = 99
        assert target.modes[0].speed == 3.0

    def test_committing_a_list_writes_into_the_existing_nodes(self, session, target):
        original = target.modes[0]
        session.draft.modes[0].speed = 99
        session.commit()
        assert target.modes[0] is original
        assert original.speed == 99


class TestTransientFields:
    """Fields a session must not treat as settings.

    ``ContextDefinition.movementMode`` is *published* by the navigation manager
    -- which mode is in force right now -- rather than chosen by a player.  A
    draft that copied it would write a stale value back on Apply, and if the
    world had imposed a different kind of mode meanwhile it would replace the
    live node with a copy, breaking the identity the manager compares by.
    """

    def test_a_transient_field_is_not_copied_into_the_draft(self):
        target = Settings(walk=Walk(name='swim'))
        type(target).TRANSIENT_FIELDS = ('walk',)
        try:
            session = SettingsSession(target)
            assert not session.draft.walk
        finally:
            del type(target).TRANSIENT_FIELDS

    def test_a_transient_field_is_not_written_back(self):
        target = Settings(walk=Walk(name='swim'))
        original = target.walk
        type(target).TRANSIENT_FIELDS = ('walk',)
        try:
            session = SettingsSession(target)
            session.draft.lights = 9
            session.commit()
        finally:
            del type(target).TRANSIENT_FIELDS
        assert target.walk is original
        assert target.lights == 9

    def test_a_transient_field_does_not_make_a_session_dirty(self):
        target = Settings(walk=Walk(name='swim'))
        type(target).TRANSIENT_FIELDS = ('walk',)
        try:
            session = SettingsSession(target)
            target.walk = Walk(name='fly')
            assert not session.dirty
        finally:
            del type(target).TRANSIENT_FIELDS

    def test_the_context_definition_declares_the_mode_in_force_transient(self):
        from OpenGLContext.contextdefinition import ContextDefinition
        assert 'movementMode' in ContextDefinition.TRANSIENT_FIELDS


class TestChildSessions:
    def test_a_child_edits_a_copy_of_the_parents_draft(self, session):
        child = session.child('walk')
        assert child.draft is not session.draft.walk
        assert child.draft.speed == session.draft.walk.speed

    def test_a_child_commit_is_not_a_save(self, session, target):
        child = session.child('walk')
        child.draft.speed = 8.0
        child.commit()
        assert session.draft.walk.speed == 8.0
        assert target.walk.speed == 2.0

    def test_only_the_outermost_commit_reaches_the_real_node(self, session, target):
        child = session.child('walk')
        child.draft.speed = 8.0
        child.commit()
        session.commit()
        assert target.walk.speed == 8.0

    def test_cancelling_the_parent_after_applying_the_child_changes_nothing(
            self, session, target):
        """The failure this design exists to prevent."""
        child = session.child('walk')
        child.draft.speed = 8.0
        child.commit()
        session.revert()
        assert target.walk.speed == 2.0

    def test_a_child_revert_leaves_the_parent_untouched(self, session):
        child = session.child('walk')
        child.draft.speed = 8.0
        child.revert()
        assert session.draft.walk.speed == 2.0

    def test_a_committed_child_makes_its_parent_dirty(self, session):
        """So the settings screen's Apply lights up for an edit two dialogs deep."""
        child = session.child('walk')
        child.draft.speed = 8.0
        assert not session.dirty
        child.commit()
        assert session.dirty

    def test_a_reverted_child_leaves_the_parent_clean(self, session):
        child = session.child('walk')
        child.draft.speed = 8.0
        child.revert()
        assert not session.dirty

    def test_a_child_of_a_list_entry_is_addressed_by_index(self, session, target):
        child = session.child('modes', index=1)
        assert child.draft.name == 'run'
        child.draft.speed = 12.0
        child.commit()
        session.commit()
        assert target.modes[1].speed == 12.0
        assert target.modes[0].speed == 3.0

    def test_a_child_can_be_taken_of_any_node_in_the_draft(self, session):
        child = session.child(node=session.draft.walk)
        child.draft.speed = 5.0
        child.commit()
        assert session.draft.walk.speed == 5.0

    def test_asking_for_a_child_of_nothing_raises(self, session):
        session.draft.walk = None
        with pytest.raises(ValueError):
            session.child('walk')

    def test_a_grandchild_only_saves_at_the_top(self, session, target):
        child = session.child('walk')
        grandchild = child.child(node=child.draft)
        grandchild.draft.speed = 4.0
        grandchild.commit()
        child.commit()
        assert target.walk.speed == 2.0
        session.commit()
        assert target.walk.speed == 4.0


class TestNotification:
    def test_a_session_reports_when_it_becomes_dirty(self, session):
        seen = []
        session.on_dirty = seen.append
        session.draft.lights = 1
        assert seen == [session]

    def test_a_child_commit_reports_on_the_parent(self, session):
        seen = []
        session.on_dirty = seen.append
        child = session.child('walk')
        child.draft.speed = 8.0
        child.commit()
        assert seen == [session]


class TestDirtyIsCheapToAsk:
    """``dirty`` is asked on every keystroke of a slider drag.

    Answering it with a deep comparison of the whole definition -- every
    movement mode, every key binding under them -- on every mouse-move event is
    work the session already has the answer to.
    """

    def test_a_fresh_session_is_clean(self):
        session = SettingsSession(Settings())
        assert not session.dirty

    def test_an_edit_makes_it_dirty(self):
        session = SettingsSession(Settings())
        session.draft.lights = 2
        assert session.dirty

    def test_committing_makes_it_clean_again(self):
        session = SettingsSession(Settings())
        session.draft.lights = 2
        session.commit()
        assert not session.dirty

    def test_reverting_makes_it_clean_again(self):
        session = SettingsSession(Settings())
        session.draft.lights = 2
        session.revert()
        assert not session.dirty

    def test_a_change_in_a_sub_record_reaches_the_parent(self):
        settings = Settings()
        settings.walk = Walk()
        session = SettingsSession(settings)
        child = session.child('walk')
        child.draft.speed = 9.0
        child.commit()
        assert session.dirty

    def test_asking_again_does_not_walk_the_tree_again(self, monkeypatch):
        """Nothing between two edits can change the answer, so it is kept."""
        from OpenGLContext.ui import session as session_module
        session = SettingsSession(Settings())
        calls = []
        real = session_module.nodes_equal
        monkeypatch.setattr(session_module, 'nodes_equal',
                            lambda a, b: calls.append(1) or real(a, b))
        for _ in range(20):
            assert not session.dirty
        assert len(calls) == 1, "compared the whole tree once per question"

    def test_an_edit_makes_it_work_the_answer_out_again(self, monkeypatch):
        from OpenGLContext.ui import session as session_module
        session = SettingsSession(Settings())
        assert not session.dirty
        session.draft.lights = 2
        assert session.dirty

    def test_setting_a_value_back_by_hand_puts_it_out_again(self):
        settings = Settings()
        session = SettingsSession(settings)
        original = int(session.draft.lights)
        session.draft.lights = original + 1
        assert session.dirty
        session.draft.lights = original
        assert not session.dirty


class TestASessionCanBeClosed:
    """A dialog that has gone stops being told about its own draft."""

    def test_closing_stops_the_notifications(self):
        session = SettingsSession(Settings())
        seen = []
        session.on_dirty = seen.append
        session.draft.lights = 2
        assert seen
        session.close()
        seen.clear()
        session.draft.lights = 3
        assert not seen, "a closed session is still listening"

    def test_it_can_be_used_as_a_context_manager(self):
        seen = []
        with SettingsSession(Settings()) as session:
            session.on_dirty = seen.append
            session.draft.lights = 2
        assert seen
        seen.clear()
        session.draft.lights = 4
        assert not seen

    def test_closing_twice_is_harmless(self):
        session = SettingsSession(Settings())
        session.close()
        session.close()
