"""``check_scaling`` passes work that grows as it should, and fails work that grows faster."""
import pytest

from OpenGLContext.testing.scaling import (
    ScalingExceeded,
    check_scaling,
    measure_scaling,
)


def _pairs(n):
    """Work that compares every one of ``n`` items with every other: n squared."""
    items = list(range(n))
    return lambda: sum(1 for a in items for b in items if a == b)


def _counting(power):
    return lambda n: (lambda: n ** power)


def test_linear_work_passes_a_linear_bound():
    found = check_scaling(_counting(1), n=100, most=4.5, measure='count')
    assert found.ratio == pytest.approx(4.0)
    assert found.sizes == (100, 400)


def test_quadratic_work_fails_a_linear_bound():
    with pytest.raises(ScalingExceeded, match='16.00 times as much; the bound is 4.50'):
        check_scaling(_counting(2), n=100, most=4.5, measure='count')


def test_the_factor_is_the_callers():
    found = check_scaling(_counting(1), n=10, factor=2, most=2.0, measure='count')
    assert found.sizes == (10, 20)


def test_work_that_costs_nothing_scales_as_nothing():
    assert measure_scaling(lambda n: (lambda: 0), n=5, measure='count').ratio == 1.0
    assert measure_scaling(lambda n: (lambda: n - 5), n=5,
                           measure='count').ratio == float('inf')


def test_each_size_is_run_once_before_it_is_measured():
    calls = []

    def prepare(n):
        def work():
            calls.append(n)
            return len(calls)
        return work
    measure_scaling(prepare, n=3, measure='count')
    assert calls == [3, 3, 12, 12]


@pytest.mark.serial
def test_time_is_measured_as_the_least_of_several_runs():
    found = check_scaling(_pairs, n=60, most=40.0, repeat=3)
    assert found.measure == 'time'
    assert 4.0 < found.ratio
    assert ' s and ' in str(found)


@pytest.mark.parametrize('named', [
    {'measure': 'memory'}, {'n': 0}, {'factor': 1},
])
def test_a_question_that_cannot_be_asked_is_refused(named):
    arguments = {'n': 10, 'factor': 4, 'measure': 'count'}
    arguments.update(named)
    with pytest.raises(ValueError):
        measure_scaling(_counting(1), **arguments)


def test_the_plugin_offers_it_as_a_fixture(check_scaling):
    assert check_scaling(_counting(1), n=10, most=4.5, measure='count').ratio == 4.0


def test_the_fixture_refuses_a_timed_test_without_the_serial_marker(check_scaling):
    with pytest.raises(pytest.fail.Exception, match='serial'):
        check_scaling(_pairs, n=10, most=100.0)
