from unittest import TestCase
from apps.assistant.tool_inputs import validated_arguments


class ToolInputTests(TestCase):
    def test_rejects_missing_query_extra_fields_and_non_json(self):
        for raw in ['{"queries":["PINN"]}', '{"query":"PINN","path":"/tmp/x"}', 'not json', '[]']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validated_arguments('search_knowledge', raw, {})

    def test_rejects_guessed_source_and_invalid_budgets(self):
        for raw in ['{"source_ref":"S999"}', '{"source_ref":"S1","budget":true}',
                    '{"source_ref":"S1","budget":3001}', '{"source_ref":"S1","offset":-1}']:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validated_arguments('read_evidence', raw, {'S1': {}})

    def test_valid_source_query_is_preserved_without_expanding_scope(self):
        self.assertEqual(validated_arguments('find_in_source', '{"source_ref":"S1","query":"appendix"}', {'S1': {}}),
                         {'source_ref': 'S1', 'query': 'appendix'})
