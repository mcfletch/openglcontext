"""Values read out of a document: what a reader answers for each kind of input.

:class:`~OpenGLContext.loaders.documentvalues.DocumentValues` is what every
reader of a model's custom properties goes through, so a value that is
misspelt, infinite or out of range becomes a default or a bound and a report,
never an exception out of the load.
"""
import logging
import math

import pytest

from OpenGLContext.loaders.documentvalues import (
    DocumentError, DocumentValues, bounded, parse_object, require_array,
    require_index, require_item, require_number, require_numbers, require_object,
    require_text, require_whole,
)


@pytest.fixture
def said():
    return []


@pytest.fixture
def values(said):
    return DocumentValues(warn=said.append)


# --- numbers ------------------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    (2, 2.0), (2.5, 2.5), ('2.5', 2.5), (' 3 ', 3.0),
])
def test_a_number_is_read(values, said, raw, expected):
    assert values.number(raw, 1.0, 'depth') == expected
    assert said == []


def test_an_absent_number_is_the_default_without_a_report(values, said):
    assert values.number(None, 1.5, 'depth') == 1.5
    assert said == []


@pytest.mark.parametrize('raw', [
    'deep', [1.0], {}, True, float('nan'), float('inf'), -float('inf'),
    'nan', 'inf', 10 ** 400,
])
def test_what_is_no_finite_number_is_the_default_and_reported(values, said, raw):
    assert values.number(raw, 1.5, 'depth') == 1.5
    assert len(said) == 1
    assert 'depth' in said[0]


@pytest.mark.parametrize('raw, expected', [(-1.0, 0.0), (7.0, 5.0), (3.0, 3.0)])
def test_a_number_outside_its_bounds_is_the_nearer_bound(values, said, raw, expected):
    assert values.number(raw, 1.0, 'depth', minimum=0.0, maximum=5.0) == expected
    assert len(said) == (0 if raw == expected else 1)


def test_one_bound_alone_is_enough(values):
    assert values.number(-3, 1.0, 'depth', minimum=0.0) == 0.0
    assert values.number(1e9, 1.0, 'depth', maximum=10.0) == 10.0


# --- whole numbers ------------------------------------------------------------

@pytest.mark.parametrize('raw', [2, 2.0, '2', '2.0'])
def test_a_whole_number_is_read(values, said, raw):
    assert values.integer(raw, 0, 'priority') == 2
    assert said == []


@pytest.mark.parametrize('raw', ['hi', 2.5, float('inf'), float('nan'), 1e999, None])
def test_what_is_no_whole_number_is_the_default(values, said, raw):
    assert values.integer(raw, 3, 'interval') == 3
    assert len(said) == (0 if raw is None else 1)


def test_a_whole_number_is_clamped(values):
    assert values.integer(0, 3, 'interval', minimum=1) == 1
    assert values.integer(10 ** 12, 3, 'budget', maximum=20000) == 20000


# --- flags --------------------------------------------------------------------

@pytest.mark.parametrize('raw, expected', [
    (True, True), (False, False), (1, True), (0, False), (0.0, False),
    ('true', True), ('False', False), (' YES ', True), ('off', False),
    ('1', True), ('0', False),
])
def test_a_flag_is_read(values, said, raw, expected):
    assert values.flag(raw, not expected, 'hemisphere') is expected
    assert said == []


@pytest.mark.parametrize('raw', ['maybe', [], {}, float('nan')])
def test_what_is_no_flag_is_the_default(values, said, raw):
    assert values.flag(raw, True, 'hemisphere') is True
    assert len(said) == 1


# --- names --------------------------------------------------------------------

def test_a_choice_is_one_of_its_options(values, said):
    assert values.choice(' Slime ', 'water', 'medium', ('water', 'slime')) == 'slime'
    assert said == []


@pytest.mark.parametrize('raw', ['mud', 3, None])
def test_what_is_no_option_is_the_default(values, said, raw):
    assert values.choice(raw, 'water', 'medium', ('water', 'slime')) == 'water'
    assert len(said) == (0 if raw is None else 1)


# --- vectors ------------------------------------------------------------------

def test_a_vector_is_its_numbers(values, said):
    assert values.vector([1, '2', 3.5], (0, 0, 0), 'position') == (1.0, 2.0, 3.5)
    assert said == []


@pytest.mark.parametrize('raw', [[1.0], [1, 2, 3, 4], 'abc', [1, 'x', 2],
                                 [1, float('nan'), 2]])
def test_what_is_no_vector_is_the_default(values, said, raw):
    assert values.vector(raw, (0.0, 0.0, 0.0), 'position') == (0.0, 0.0, 0.0)
    assert len(said) == 1


def test_a_list_of_vectors_is_their_numbers(values, said):
    raw = [[0, 1], ['2', 3.5]]
    assert values.vectors(raw, 'route points', length=2) == [(0.0, 1.0), (2.0, 3.5)]
    assert said == []


def test_a_vector_in_a_list_that_is_no_vector_is_left_out(values, said):
    """Put in its place, a default would move a road's corner to the origin."""
    raw = [[0, 1], [3], [1, 'x'], None, [2, 2]]
    assert values.vectors(raw, 'route points', length=2) == [(0.0, 1.0), (2.0, 2.0)]
    assert len(said) == 3


@pytest.mark.parametrize('raw, reports', [(None, 0), ('abc', 1), ({'a': 1}, 1)])
def test_what_is_no_list_is_no_vectors(values, said, raw, reports):
    assert values.vectors(raw, 'route points', length=2) == []
    assert len(said) == reports


# --- structure ----------------------------------------------------------------

def test_a_mapping_is_itself(values, said):
    raw = {'depth': 2}
    assert values.mapping(raw, 'water') is raw
    assert values.mapping(None, 'water') == {}
    assert said == []


@pytest.mark.parametrize('raw', [[1, 2], 'deep', 3, {1: 'x'}])
def test_what_is_no_mapping_is_empty_and_reported(values, said, raw):
    assert values.mapping(raw, 'water') == {}
    assert len(said) == 1
    assert 'water' in said[0]


def test_an_array_is_its_items(values, said):
    assert values.array([1, 'x'], 'children') == [1, 'x']
    assert values.array((1,), 'children') == (1,)
    assert values.array(None, 'children') == ()
    assert said == []


@pytest.mark.parametrize('raw', ['abc', {'a': 1}, 3])
def test_what_is_no_array_is_empty_and_reported(values, said, raw):
    assert values.array(raw, 'children') == ()
    assert len(said) == 1


def test_a_text_is_a_string(values, said):
    assert values.text('lake', 'pond', 'name') == 'lake'
    assert values.text(None, 'pond', 'name') == 'pond'
    assert said == []


@pytest.mark.parametrize('raw', [3, ['lake'], {'a': 'b'}])
def test_what_is_no_text_is_the_default_and_reported(values, said, raw):
    assert values.text(raw, 'pond', 'name') == 'pond'
    assert len(said) == 1


def test_texts_are_a_list_of_strings(values, said):
    assert values.texts(['a', 'b'], ('c',), 'keys') == ['a', 'b']
    assert values.texts(None, ('c',), 'keys') == ['c']
    assert said == []


@pytest.mark.parametrize('raw', ['a', ['a', 2], {'a': 1}])
def test_what_is_no_list_of_texts_is_the_default_and_reported(values, said, raw):
    assert values.texts(raw, ('c',), 'keys') == ['c']
    assert len(said) == 1


def test_a_document_that_must_have_a_part_is_refused_without_it():
    assert require_object({'a': 1}, 'root') == {'a': 1}
    assert require_array([1], 'children') == [1]
    assert require_numbers([1, '2', 3], 'box', 3) == (1.0, 2.0, 3.0)
    with pytest.raises(DocumentError, match='root is None, which is not an object'):
        require_object(None, 'root')
    with pytest.raises(DocumentError, match='children is .abc., which is not an array'):
        require_array('abc', 'children')
    with pytest.raises(DocumentError, match='box is .1, 2., which is not 3 finite numbers'):
        require_numbers([1, 2], 'box', 3)
    with pytest.raises(DocumentError, match='box is .x., which is not 3 finite numbers'):
        require_numbers('x', 'box', 3)
    assert require_number('2.5', 'geometricError') == 2.5
    assert require_text('a.glb', 'uri') == 'a.glb'
    with pytest.raises(DocumentError, match='geometricError is None, which is not a finite'):
        require_number(None, 'geometricError')
    with pytest.raises(DocumentError, match='geometricError is True, which is not a finite'):
        require_number(True, 'geometricError')
    with pytest.raises(DocumentError, match='uri is 7, which is not a string'):
        require_text(7, 'uri')
    assert require_whole('3', 'count') == 3
    assert require_index(0, 'mesh') == 0
    document = {'meshes': [{'name': 'a'}, 'b']}
    assert require_item(document, 'meshes', 0) == {'name': 'a'}
    with pytest.raises(DocumentError, match='count is 1.5, which is not a whole'):
        require_whole(1.5, 'count')
    with pytest.raises(DocumentError, match='mesh is -1, which is negative'):
        require_index(-1, 'mesh')
    with pytest.raises(DocumentError, match='meshes 2 is named and there are 2'):
        require_item(document, 'meshes', 2)
    with pytest.raises(DocumentError, match="meshes 1 is 'b', which is not an object"):
        require_item(document, 'meshes', 1)
    assert issubclass(DocumentError, ValueError)


def test_a_document_parses_to_an_object():
    assert parse_object(b'{"asset": {"version": "1.1"}}', 'tileset') == {
        'asset': {'version': '1.1'}}
    assert parse_object('{}', 'tileset') == {}
    with pytest.raises(DocumentError, match='tileset is not a JSON object'):
        parse_object('[1, 2]', 'tileset')
    with pytest.raises(DocumentError, match='tileset is not JSON'):
        parse_object(b'{"asset"', 'tileset')
    with pytest.raises(DocumentError, match='tileset is not JSON'):
        parse_object(b'\xff\xfe', 'tileset')


# --- reporting ----------------------------------------------------------------

def test_a_problem_is_reported_once_per_reader(values, said):
    for _ in range(100):
        values.number('deep', 0.0, 'depth')
    assert len(said) == 1


def test_without_warn_a_report_is_logged_on_the_given_logger(caplog):
    logger = logging.getLogger('OpenGLContext.tests.documentvalues')
    values = DocumentValues(logger=logger)
    with caplog.at_level(logging.WARNING, logger=logger.name):
        values.number('deep', 0.0, 'water depth')
        values.number('deep', 0.0, 'water depth')
    records = [r for r in caplog.records if r.name == logger.name]
    assert len(records) == 1
    assert 'water depth' in records[0].getMessage()


# --- bounded ------------------------------------------------------------------

@pytest.mark.parametrize('value, expected', [
    (0.3, 0.3), (float('nan'), 0.5), (float('inf'), 0.5), ('x', 0.5),
    (None, 0.5), (-2.0, 0.05), (4.0, 1.0),
])
def test_bounded_answers_a_finite_number_inside_the_bounds(value, expected):
    assert bounded(value, 0.5, 0.05, 1.0) == expected
    assert math.isfinite(bounded(value, 0.5))
