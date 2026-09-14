"""Server-owned source attribution contracts; not a semantic fact checker."""
import re


RULES = {
    'paper_fulltext': '论文原文片段；仅陈述实际看到的部分，不能把主要改成仅、可能改成已经证明。',
    'paper_abstract': '论文摘要；只能称摘要报告，不能称已查阅正文或实验细节。',
    'derived_research_card': '衍生整理卡；必须注明整理卡转述或解读，不能冒充论文原文。',
    'agent_summary': 'Agent 摘要；属于模型生成的二手内容，必须明确归属，不能冒充原文或实测。',
}


def review_sources(sources):
    return [{**source, 'attribution_rule': RULES.get(source.get('source_kind'),
             '按 source_kind 描述当前记录；不是已核对的论文原文，不得推定论文或实测来源。')}
            for source in sources.values()]


def validate_attribution(answer, sources):
    """Catch explicit fulltext claims supported exclusively by secondary sources.

    This intentionally narrow gate does not decide whether a primary excerpt
    entails the claim. Mixed citations, implicit attribution and scientific
    qualifiers still require evaluation against the evidence.
    """
    for sentence in re.split(r'[。！？\n]', answer):
        if not re.search(r'原文(?:采用|使用|明确|指出|提到|报告|已经|在|中|主要|仅|只)', sentence):
            continue
        labels = re.findall(r'\[(S\d+)\]', sentence)
        if not labels:
            continue  # Citation existence and completeness are separate checks.
        cited = [sources[label] for label in labels if label in sources]
        if any(s.get('source_kind') == 'paper_fulltext' for s in cited):
            continue
        if re.search(r'(?:整理卡|摘要|二手材料)(?:转述|解读|记载|称|报告)', sentence):
            continue
        raise ValueError('二手或未分类来源不能冒充论文原文')
