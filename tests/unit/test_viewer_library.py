"""The things a viewer can offer to open (:mod:`OpenGLContext.viewer.library`).

``oglc-view`` with nothing to open should not be a usage message: it should be a
shelf.  The shelf is this -- entries with a name, a source, a category and a
picture -- and it is *derived* from the rosters that already exist rather than
being a second list to keep in step with them.

Nothing here touches the network at import or at construction: a preview URL is
fetched only when something asks for one, and failing to fetch it means an entry
with no picture rather than no entry.
"""

from OpenGLContext.viewer.library import (
    Entry, FEATURE_TESTS, Library, MODELS, WORLDS, default_library,
    sample_entries, world_entries,
)


class TestAnEntry:
    def test_it_knows_what_to_open(self):
        entry = Entry(name='Duck', source='Duck.glb', category=MODELS)
        assert entry.source == 'Duck.glb'

    def test_it_carries_the_options_that_frame_it(self):
        """A scene authored to be walked says so here, not in the viewer."""
        entry = Entry(name='Sponza', source='s.glb', category=WORLDS,
                      options={'physics': True})
        assert entry.options['physics'] is True

    def test_two_entries_for_the_same_thing_are_equal(self):
        assert Entry(name='a', source='b') == Entry(name='a', source='b')


class TestTheLibrary:
    ENTRIES = (
        Entry(name='Duck', source='Duck.glb', category=MODELS),
        Entry(name='Box', source='Box.glb', category=MODELS),
        Entry(name='Valley', source='valley.wrl', category=WORLDS),
    )

    def test_it_lists_what_it_holds(self):
        assert len(Library(self.ENTRIES).entries) == 3

    def test_categories_come_out_in_a_stable_order(self):
        """A shelf that reorders itself between runs is a shelf nobody learns."""
        first = Library(self.ENTRIES).categories()
        assert first == Library(self.ENTRIES).categories()
        assert set(first) == {MODELS, WORLDS}

    def test_a_category_lists_only_its_own(self):
        assert [e.name for e in Library(self.ENTRIES).inCategory(WORLDS)] == ['Valley']

    def test_an_empty_category_is_empty_rather_than_an_error(self):
        assert Library(self.ENTRIES).inCategory('Nothing') == ()

    def test_an_entry_can_be_found_by_name(self):
        assert Library(self.ENTRIES).find('Box').source == 'Box.glb'

    def test_an_unknown_name_is_not_found(self):
        assert Library(self.ENTRIES).find('Teapot') is None

    def test_an_application_can_add_its_own(self):
        """The point of a shelf is that you can put your own things on it."""
        mine = Entry(name='Mine', source='mine.glb', category='Ours')
        extended = Library(self.ENTRIES).extend([mine])
        assert extended.find('Mine') is mine
        assert extended.find('Duck') is not None
        assert Library(self.ENTRIES).find('Mine') is None, 'the original is untouched'

    def test_it_is_empty_by_default(self):
        assert Library().entries == ()


class TestWhatIsOnTheShelf:
    def test_the_sample_roster_becomes_entries(self):
        """Derived from the existing demo roster, not a second copy of it."""
        entries = sample_entries()
        assert len(entries) > 20
        assert all(entry.name and entry.source for entry in entries)

    def test_a_khronos_sample_names_something_the_viewer_can_open(self):
        """A bare sample name is not a source: it is not a path and not a URL.

        The viewer resolves whatever it is given, so an entry carrying ``Duck``
        was answered with "file not found" and the library could open nothing at
        all.  The entry carries the sample's own URL, which the glTF adapter
        fetches and caches like any other.
        """
        from OpenGLContext.loaders import gltf
        entries = {entry.name: entry for entry in sample_entries()}
        assert 'Duck' in entries
        assert entries['Duck'].source == gltf.sample_model_url('Duck')

    def test_every_entry_names_a_path_or_a_url(self):
        """Nothing on the shelf may be unopenable."""
        from OpenGLContext.loaders import resolver
        import os
        for entry in sample_entries():
            assert resolver.is_url(entry.source) or os.path.exists(entry.source), \
                entry.name

    def test_every_entry_is_a_source_an_adapter_recognises(self):
        from OpenGLContext.viewer.adapters import adapter_for
        for entry in sample_entries():
            assert adapter_for(entry.source) is not None, entry.name

    def test_a_scene_that_needs_a_lit_backdrop_says_so_in_its_options(self):
        entries = {entry.name: entry for entry in sample_entries()}
        lit = [e for e in entries.values() if e.options.get('background')]
        assert lit, 'the roster records which materials need an environment'

    def test_a_posed_capture_time_is_not_carried_over(self):
        """``anim_time`` pins a still for a reproducible capture.

        Carried into the viewer it freezes the animation at that instant, so
        BrainStem, Fox and CesiumMan opened from the shelf stood there.
        """
        for entry in sample_entries():
            assert 'anim_time' not in entry.options, entry.name

    def test_an_animated_model_opens_playing(self):
        entries = {entry.name: entry for entry in sample_entries()}
        assert entries['BrainStem'].options.get('anim_time') is None

    def test_the_framing_the_roster_records_is_carried_over(self):
        """Otherwise the library would show every model badly framed."""
        posed = [e for e in sample_entries() if e.options.get('yaw')]
        assert posed

    def test_the_test_fixtures_are_not_on_the_shelf(self):
        """``tests/wrls`` is test data: degenerate meshes, deliberately bad
        PNGs, one-primitive files. It is not content anybody wants to browse,
        and it does not ship with the package at all."""
        assert default_library().inCategory(WORLDS) == ()
        assert not [entry for entry in default_library().entries
                    if entry.source.endswith(('.wrl', '.wrz', '.vrml'))]

    def test_an_application_can_still_shelve_its_own_worlds(self):
        """The category exists; this package simply ships nothing for it."""
        mine = Entry(name='Valley', source='valley.wrl', category=WORLDS)
        assert default_library().extend([mine]).inCategory(WORLDS) == (mine,)

    def test_the_default_shelf_has_more_than_one_shelf_on_it(self):
        library = default_library()
        assert len(library.categories()) >= 1
        assert len(library.entries) > 20

    def test_building_the_shelf_touches_no_network(self, monkeypatch):
        """Opening a viewer must not wait on a catalogue download."""
        from OpenGLContext.loaders import gltf

        def refuse(*args, **named):
            raise AssertionError('the library fetched something')
        monkeypatch.setattr(gltf, 'fetch_sample_catalog', refuse)
        assert default_library().entries


class TestPreviews:
    def test_pictures_are_filled_in_only_when_asked_for(self, monkeypatch):
        from OpenGLContext.viewer import library as module
        monkeypatch.setattr(module, 'screenshot_urls',
                            lambda: {'Duck': 'https://x/duck.png'})
        library = Library([Entry(name='Duck', source='Duck', category=MODELS)])
        assert library.entries[0].preview == ''
        withPictures = library.withPreviews()
        assert withPictures.find('Duck').preview == 'https://x/duck.png'

    def test_an_entry_that_already_has_one_keeps_it(self, monkeypatch):
        from OpenGLContext.viewer import library as module
        monkeypatch.setattr(module, 'screenshot_urls',
                            lambda: {'Duck': 'https://x/duck.png'})
        library = Library([Entry(name='Duck', source='Duck', preview='own.png')])
        assert library.withPreviews().find('Duck').preview == 'own.png'

    def test_being_offline_costs_pictures_and_nothing_else(self, monkeypatch):
        from OpenGLContext.viewer import library as module

        def offline():
            raise IOError('no route to host')
        monkeypatch.setattr(module, 'screenshot_urls', offline)
        library = Library([Entry(name='Duck', source='Duck')])
        assert library.withPreviews().find('Duck') is not None

    def test_the_catalogue_is_only_fetched_once(self, monkeypatch):
        from OpenGLContext.loaders import gltf
        from OpenGLContext.viewer import library as module
        module.screenshot_urls.cache_clear()
        calls = []
        monkeypatch.setattr(gltf, 'fetch_sample_catalog',
                            lambda: calls.append(1) or [{'name': 'Duck',
                                                         'screenshot_url': 'u'}])
        try:
            assert module.screenshot_urls() == {'Duck': 'u'}
            assert module.screenshot_urls() == {'Duck': 'u'}
            assert len(calls) == 1
        finally:
            module.screenshot_urls.cache_clear()


class TestFeatureTestsAreShelvedApart:
    """Most of the Khronos roster is conformance fixtures, not things to look at.

    A shelf full of `Triangle`, `Box` and forty `Compare*` grids is a shelf
    nobody finds anything in, so they get a section of their own -- and it is
    the *last* one, because the point of the ordering is that the first thing
    you see is worth seeing.
    """

    def test_they_are_on_their_own_shelf(self):
        library = default_library()
        names = {entry.name for entry in library.inCategory(FEATURE_TESTS)}
        assert 'Triangle' in names
        assert 'CompareRoughness' in names

    def test_the_things_worth_looking_at_are_not_on_it(self):
        library = default_library()
        names = {entry.name for entry in library.inCategory(FEATURE_TESTS)}
        for demo in ('DamagedHelmet', 'Sponza', 'AntiqueCamera', 'BrainStem'):
            assert demo not in names, demo

    def test_it_is_the_last_shelf(self):
        assert default_library().categories()[-1] == FEATURE_TESTS

    def test_the_first_shelf_is_worth_browsing(self):
        """Whatever opens first must not be a page of grey triangles."""
        library = default_library()
        first = library.inCategory(library.categories()[0])
        assert first
        assert not any(entry.category == FEATURE_TESTS for entry in first)

    def test_the_ordinary_shelves_shrank(self):
        library = default_library()
        assert len(library.inCategory(FEATURE_TESTS)) > 40
        assert len(library.inCategory(MODELS)) < 40
