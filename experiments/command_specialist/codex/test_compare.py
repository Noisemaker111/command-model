"""Comparison invariants: failed or mismatched runs cannot imply savings."""
import unittest
from compare import compare


class ComparisonInvariants(unittest.TestCase):
    def test_failed_work_has_no_savings_claim(self):
        common = {'case': 'csv', 'model': 'same', 'effort': 'low', 'success': False}
        result = compare(dict(common, arm='baseline'), dict(common, arm='delegated'))
        self.assertIsNone(result['savings'])

    def test_different_frontier_settings_are_not_a_pair(self):
        with self.assertRaises(ValueError):
            compare({'case': 'csv', 'model': 'a', 'effort': 'low'},
                    {'case': 'csv', 'model': 'b', 'effort': 'low'})


if __name__ == '__main__':
    unittest.main()
