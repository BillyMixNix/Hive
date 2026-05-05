from reflector import Reflector


def test_reflector_evaluate_simple():
    r = Reflector()
    result = r.evaluate({"dummy": "value"})
    assert isinstance(result, dict)
    assert result.get('verdict') in {"accept", "revise", "reject"}
    assert isinstance(result.get('confidence'), float)
