"""Portable-iterator contract audit, committed before V4 outcome inspection.

The original frozen score is retained. This supplemental audit may veto a
correctness claim; it cannot rescue a failed original confirmation decision.
"""
import re


def test_source(case):
    if case["family"] != "single_pass":
        raise ValueError("iterator cases only")
    variant = int(case["id"].rsplit("_", 1)[1])
    module = next(p[:-3] for p in case["files"] if not p.startswith("test_"))
    if not re.fullmatch(r"component_[a-f0-9]{8}", module):
        raise ValueError("unexpected source module")
    common = f'''from {module} import summarize_{variant} as summarize
import pytest

class PortableIterator:
    def __init__(self, values):
        self.remaining = iter(values)
    def __iter__(self):
        return self
    def __next__(self):
        return next(self.remaining)
    def __reduce__(self):
        raise TypeError('This valid iterator is not serializable')

def generator(values):
    yield from values

FACTORIES = (iter, generator, PortableIterator)

'''
    if variant % 3 == 0:
        body = '''@pytest.mark.parametrize('factory', FACTORIES)
@pytest.mark.parametrize('values', [[], [0], [7, -3, 2], [-9, 9], [1, 1, 1]])
def test_portable_statistics(factory, values):
    stream = factory(values)
    assert summarize(stream) == {'count': len(values), 'total': sum(values)}

@pytest.mark.parametrize('factory', FACTORIES)
def test_statistics_respect_current_cursor(factory):
    stream = factory([99, 7, -3, 2])
    next(stream)
    assert summarize(stream) == {'count': 3, 'total': 6}
'''
    elif variant % 3 == 1:
        body = '''@pytest.mark.parametrize('factory', FACTORIES)
@pytest.mark.parametrize('values', [[], [0], [7, 0, 2], [9], [1, 1, 1]])
def test_portable_validation(factory, values):
    assert summarize(factory(values)) == tuple(values)

@pytest.mark.parametrize('factory', FACTORIES)
def test_validation_respects_current_cursor(factory):
    stream = factory([99, 7, 0, 2])
    next(stream)
    assert summarize(stream) == (7, 0, 2)

@pytest.mark.parametrize('factory', FACTORIES)
def test_portable_negative_rejection(factory):
    with pytest.raises(ValueError):
        summarize(factory([7, -1, 2]))
'''
    else:
        body = '''@pytest.mark.parametrize('factory', FACTORIES)
@pytest.mark.parametrize('values', [[], [('a', 0)], [('a', 7), ('b', -3), ('a', 2)]])
def test_portable_dictionary(factory, values):
    assert summarize(factory(values)) == dict(values)

@pytest.mark.parametrize('factory', FACTORIES)
def test_dictionary_respects_current_cursor(factory):
    stream = factory([('unused', 99), ('a', 7), ('a', 2)])
    next(stream)
    assert summarize(stream) == {'a': 2}
'''
    return common + body
