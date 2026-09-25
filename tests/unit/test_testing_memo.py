"""``check_memo_inputs`` fails a memo that misses an input, and passes one that does not."""
import numpy as np
import pytest

from OpenGLContext.testing.memo import MemoMissedInputs, check_memo_inputs


class _Scene:
    def __init__(self):
        self.a = 1
        self.b = 2
        self.c = 3


def _computation(scene):
    return scene.a + 10 * scene.b + 100 * scene.c


def _memo(scene, watched):
    """A memo keyed on the named attributes only."""
    held = {}

    def ask():
        key = tuple(getattr(scene, name) for name in watched)
        if 'key' not in held or held['key'] != key:
            held['key'] = key
            held['answer'] = _computation(scene)
        return held['answer']
    return ask


def _edits(scene):
    return {
        'a': lambda: setattr(scene, 'a', scene.a + 1),
        'b': lambda: setattr(scene, 'b', scene.b + 1),
        'c': lambda: setattr(scene, 'c', scene.c + 1),
    }


def test_a_memo_keyed_on_every_input_passes():
    scene = _Scene()
    check_memo_inputs(_memo(scene, 'abc'), _edits(scene),
                      fresh=lambda: _computation(scene))


def test_a_memo_missing_an_input_fails_naming_it():
    scene = _Scene()
    with pytest.raises(MemoMissedInputs) as caught:
        check_memo_inputs(_memo(scene, 'ac'), _edits(scene),
                          fresh=lambda: _computation(scene))
    assert 'b: the memo kept its answer' in str(caught.value)
    assert 'a:' not in str(caught.value)
    assert 'c:' not in str(caught.value)


def test_without_fresh_an_answer_that_stays_put_fails():
    scene = _Scene()
    with pytest.raises(MemoMissedInputs, match='^c: the memo kept'):
        check_memo_inputs(_memo(scene, 'ab'), list(_edits(scene).items()))


def test_an_edit_that_changes_nothing_is_reported_as_testing_nothing():
    scene = _Scene()
    with pytest.raises(MemoMissedInputs, match='tests nothing'):
        check_memo_inputs(_memo(scene, 'abc'), {'nothing': lambda: None},
                          fresh=lambda: _computation(scene))


def test_a_memo_that_moves_to_a_wrong_answer_fails():
    scene = _Scene()
    count = [0]

    def ask():
        count[0] += 1
        return count[0]

    with pytest.raises(MemoMissedInputs, match='answered differently'):
        check_memo_inputs(ask, _edits(scene), fresh=lambda: _computation(scene))


def test_array_answers_are_compared_element_by_element():
    scene = _Scene()
    check_memo_inputs(lambda: np.array([scene.a, scene.b]), {
        'a': lambda: setattr(scene, 'a', 5),
        'b': lambda: setattr(scene, 'b', 7),
    }, fresh=lambda: np.array([scene.a, scene.b]))


def test_no_inputs_is_a_mistake_in_the_test():
    with pytest.raises(ValueError):
        check_memo_inputs(lambda: 1, {})


def test_the_plugin_offers_it_as_a_fixture(check_memo_inputs):
    scene = _Scene()
    check_memo_inputs(_memo(scene, 'abc'), _edits(scene),
                      fresh=lambda: _computation(scene))
