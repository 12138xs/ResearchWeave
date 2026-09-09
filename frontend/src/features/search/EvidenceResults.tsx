import { Link } from 'react-router-dom';

import { evidenceSearchUrl } from '../../api/search';
import { useApiData } from '../../app/hooks';

type EvidenceResult = {
  material_id: number; title: string; version_number: number; evidence_id: number;
  page: number | null; line_start: number | null; line_end: number | null;
  review_required: boolean; reviewed_at: string | null; excerpt: string; file_url: string; url: string;
};
type EvidenceResponse = { notice: string; candidate_limit_reached: boolean; results: EvidenceResult[] };
const empty: EvidenceResponse = { notice: '', candidate_limit_reached: false, results: [] };

export function EvidenceResults({ query }: { query: string }) {
  const { data, loading, error } = useApiData<EvidenceResponse>(evidenceSearchUrl(query), empty);
  if (!query.trim()) return null;
  return <section className="search-results" aria-label="材料原文证据">
    <h2>材料原文证据</h2>
    <p>检索最新可用版本，每份材料最多展示两条证据。更多上下文可打开材料查看。</p>
    {loading ? <p>正在查找原文…</p> : error ? <p role="alert">无法检索，请使用 1–500 字的文字关键词。</p> : <>
      <p>{data.notice}</p>
      {data.candidate_limit_reached && <p>匹配范围较广，候选数量达到上限，请补充更具体的关键词。</p>}
      {data.results.map((result) => <article className="search-result-row" key={result.evidence_id}>
        <div className="search-result-content">
          <h3><Link to={result.url}>{result.title}</Link></h3>
          <p>版本 {result.version_number} · {result.page ? `第 ${result.page} 页` : `第 ${result.line_start}–${result.line_end} 行`} · {result.reviewed_at ? '已人工核对' : result.review_required ? '待核对原文' : '已提取文本'}</p>
          <p style={{ whiteSpace: 'pre-wrap' }}>{result.excerpt}</p>
          <div className="inline-actions">
            <Link to={result.url}>查看证据上下文</Link>
            <a href={result.file_url} target="_blank" rel="noreferrer">打开原文件</a>
          </div>
        </div>
      </article>)}
      {!data.results.length && <p>未找到匹配的材料证据。可换用具体术语，或先加入并解析相关材料。</p>}
    </>}
  </section>;
}
