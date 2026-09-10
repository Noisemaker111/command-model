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


class TenStageComparisonInvariants(unittest.TestCase):
    def test_failures_and_changed_sources_have_no_savings(self):
        from compare_ten import compare as compare_ten
        row = dict(arm='baseline', success=True, wall_ms=100, delegations=0,
            native_commands=1, completed_stages=10, alternate_stages=10,
            local_worker_ms=0, outside_tool_span_ms=90, local=[],
            frontier_usage={'input_tokens':100, 'cached_input_tokens':80, 'output_tokens':10},
            model='same', effort='low', benchmark_identity={'source':'frozen'})
        for changes in ({'success':False}, {'benchmark_identity':{'source':'changed'}}):
            result = compare_ten([row,dict(row,arm='chained',**changes)])['results'][1]
            self.assertFalse(result['savings_eligible'])
            self.assertNotIn('saved_ms',result)


if __name__ == '__main__':
    unittest.main()
