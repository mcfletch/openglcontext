"""Values read out of a document: what a reader answers for each kind of input.

:class:`~OpenGLContext.loaders.documentvalues.DocumentValues` is what every
reader of a model's custom properties goes through, so a value that is
misspelt, infinite or out of range becomes a default or a bound and a report,
never an exception out of the load.
"""
import logging
import math

import pytest

from OpenGLContext.loaders.documentvalues import DocumentValues, bounded


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
