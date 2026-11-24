import unittest

from research.recursive_improvement.gate import Trial, evaluate_candidate


def cases(correct_count, n=20, cost=1.0):
    return [Trial(str(i), i < correct_count, cost, 10.0) for i in range(n)]


class CandidateGateTests(unittest.TestCase):
    def test_accepts_measured_gain(self):
        result = evaluate_candidate(cases(15), cases(18))
        self.assertTrue(result.accepted)

    def test_rejects_no_gain(self):
        self.assertFalse(evaluate_candidate(cases(18), cases(18)).accepted)

    def test_rejects_cost_regression(self):
        self.assertFalse(evaluate_candidate(cases(15), cases(18, cost=2)).accepted)

    def test_rejects_mismatched_cases(self):
        with self.assertRaises(ValueError):
            evaluate_candidate(cases(15), cases(18)[:-1])

    def test_rejects_duplicate_cases(self):
        with self.assertRaises(ValueError):
            evaluate_candidate(cases(15), cases(18) + [cases(18)[0]])

    def test_rejects_negative_cost(self):
        with self.assertRaises(ValueError):
            Trial("x", True, -1, 10)


if __name__ == "__main__":
    unittest.main()
