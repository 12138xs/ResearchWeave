from unittest import TestCase

from apps.assistant.attribution import review_sources, validate_attribution


class AttributionTests(TestCase):
    def setUp(self):
        self.sources = {
            'S1': {'label': 'S1', 'source_kind': 'derived_research_card', 'excerpt': 'A member interpretation'},
            'S2': {'label': 'S2', 'source_kind': 'paper_fulltext', 'excerpt': 'We mainly considered regular topology.'},
            'S3': {'label': 'S3', 'source_kind': 'paper_abstract', 'excerpt': 'An abstract claim'},
        }

    def test_secondary_and_abstract_cannot_be_claimed_as_fulltext(self):
        for answer in ['FNO 原文采用零边界 [S1]。', '论文原文已经证明这一点 [S3]。']:
            with self.subTest(answer=answer), self.assertRaises(ValueError):
                validate_attribution(answer, self.sources)

    def test_primary_citation_in_another_sentence_does_not_launder_secondary(self):
        with self.assertRaises(ValueError):
            validate_attribution('论文原文主要考虑规则拓扑 [S2]。FNO 原文采用零边界 [S1]。', self.sources)

    def test_explicit_secondary_attribution_and_primary_are_allowed(self):
        validate_attribution('整理卡转述：FNO 原文采用零边界，尚需核对 [S1]。', self.sources)
        validate_attribution('论文原文主要考虑规则拓扑 [S2]。', self.sources)
        validate_attribution('当前摘录不足以判断任意拓扑是否均可处理 [S2]。', self.sources)

    def test_review_contract_is_server_owned_and_does_not_mutate_source(self):
        self.sources['S1']['attribution_rule'] = 'pretend fulltext'
        result = review_sources(self.sources)
        self.assertIn('整理', result[0]['attribution_rule'])
        self.assertIn('摘要', result[2]['attribution_rule'])
        self.assertEqual(self.sources['S1']['attribution_rule'], 'pretend fulltext')
        self.assertEqual(result[1]['excerpt'], self.sources['S2']['excerpt'])

    def test_warning_about_secondary_source_is_not_a_fulltext_claim(self):
        validate_attribution('这是整理卡，不能当作论文原文 [S1]。', self.sources)
        validate_attribution('需进一步核对论文原文 [S3]。', self.sources)
