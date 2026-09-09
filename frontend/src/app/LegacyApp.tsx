import { Link, NavLink, Route, Routes, useLocation, useNavigate, useParams } from 'react-router-dom';
import { type ClipboardEvent, useEffect, useMemo, useState } from 'react';

import { apiFetch, payloadMessage, readResponsePayload } from '../api/client';
import { useApiData, useAuthSession, useHealth } from './hooks';
import { EmptyState } from '../components/EmptyState';
import { DashboardHome } from '../features/home/DashboardHome';
import { Header } from '../components/Header';
import { MarkdownRenderer } from '../components/MarkdownRenderer';
import { RichTextBlock } from '../components/RichTextBlock';
import { StatusPill, statusText } from '../components/StatusPill';
import { LoginScreen } from '../features/auth/LoginScreen';
import type { AuthSession } from '../features/auth/types';
import type { Doc, DocumentListResponse, UploadedImage } from '../features/documents/types';
import { Placeholder } from '../features/home/Placeholder';
import { SearchView } from '../features/search/SearchView';
import { SettingsView } from '../features/settings/SettingsView';
import { AssistantView } from '../features/assistant/AssistantView';
import { ExperimentsView, ExperimentDetailView } from '../features/experiments/ExperimentsView';
import { MaterialsView, MaterialDetailView } from '../features/materials/MaterialsView';
import { PaperReadingPanel } from '../features/papers/PaperReadingPanel';
import { QualityIssuesView } from '../features/quality/QualityIssuesView';
import { KnowledgeSpaceMapView } from '../features/research_map/KnowledgeSpaceMapView';
import type { CatalogStats, KeywordEntry, KeywordSuggestion, KnowledgeSpace } from '../features/library/types';
import { UploadPaper } from '../features/papers/UploadPaper';
import type { Paper, PaperDeepProfile, PaperDeepProfileListResponse, PaperMetadataCandidate, PaperMetadataForm, PaperMetadataSuggestion, PaperQaHistoryItem, PaperQaHistoryResponse, PaperQaResponse, PaperReferenceImportResponse, PaperSearchResponse } from '../features/papers/types';
import { TasksView } from '../features/tasks/TasksView';
import type { TaskItem, TaskStatusResponse } from '../features/tasks/types';
import type { ThemeMode } from '../shared/types';
import { navGroups } from '../routes';

const defaultAvatar =
  'data:image/svg+xml;utf8,' +
  encodeURIComponent(
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><rect width="96" height="96" rx="48" fill="#15343b"/><circle cx="48" cy="38" r="18" fill="#8fd6c8"/><path d="M18 86c5-19 17-30 30-30s25 11 30 30" fill="#f1d6a8"/></svg>'
  );

const emptyPaperSearch: PaperSearchResponse = {
  count: 0,
  page: 1,
  page_size: 25,
  total_pages: 1,
  results: [],
  related_keywords: [],
  hot_keywords: [],
  years: []
};

const emptyDocumentList: DocumentListResponse = {
  count: 0,
  page: 1,
  page_size: 25,
  total_pages: 1,
  results: []
};

const publicationLabels: Record<string, string> = {
  article: '期刊论文',
  conference: '会议论文',
  preprint: '预印本',
  thesis: '学位论文',
  report: '技术报告',
  other: '其他'
};

function formatDate(value?: string) {
  if (!value) return '未记录';
  return new Intl.DateTimeFormat('zh-CN', { month: '2-digit', day: '2-digit' }).format(new Date(value));
}

function formatFullDate(value?: string) {
  if (!value) return '未记录';
  return new Intl.DateTimeFormat('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date(value));
}

function splitKeywords(value: string) {
  return value
    .split(/[,，;；\r\n\t]+/)
    .map((item) => item.trim())
    .filter(Boolean);
}

function buildPaperSearchUrl(filters: {
  query: string;
  status: string;
  year: string;
  readingStatus: string;
  reproductionStatus: string;
  keywords: string[];
  page: number;
  pageSize: number;
  reloadToken: number;
}) {
  const params = new URLSearchParams();
  params.set('page', String(filters.page));
  params.set('page_size', String(filters.pageSize));
  params.set('reload', String(filters.reloadToken));
  if (filters.query.trim()) params.set('q', filters.query.trim());
  if (filters.status !== 'all') params.set('status', filters.status);
  if (filters.year !== 'all') params.set('year', filters.year);
  if (filters.readingStatus !== 'all') params.set('reading_status', filters.readingStatus);
  if (filters.reproductionStatus !== 'all') params.set('reproduction_status', filters.reproductionStatus);
  if (filters.keywords.length) params.set('keywords', filters.keywords.join(','));
  return `/api/papers/search/?${params.toString()}`;
}

function buildPagedDocumentListUrl(filters: {
  spaceId: string;
  query: string;
  status: string;
  page: number;
  pageSize: number;
  reloadToken: number;
}) {
  const params = new URLSearchParams();
  if (filters.spaceId) {
    params.set('space', filters.spaceId);
    params.set('include_descendants', 'true');
  }
  params.set('page', String(filters.page));
  params.set('page_size', String(filters.pageSize));
  params.set('reload', String(filters.reloadToken));
  if (filters.query.trim()) params.set('q', filters.query.trim());
  if (filters.status !== 'all') params.set('status', filters.status);
  return `/api/documents/?${params.toString()}`;
}

function safeExternalUrl(value: string) {
  if (!value) return '';
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.href : '';
  } catch {
    return '';
  }
}

function arxivUrl(value: string) {
  return value ? `https://arxiv.org/abs/${encodeURIComponent(value)}` : '';
}

type QualityScore = {
  title: string;
  score: number | null;
  note: string;
  needsReview: boolean;
};

function extractQualityScore(items?: Array<Record<string, unknown>>): QualityScore | null {
  if (!Array.isArray(items)) return null;
  for (const item of items) {
    if (!item || typeof item !== 'object') continue;
    const title = stringifyUnknown(item.title ?? item.name ?? item.label);
    const hasQualityTitle = title.includes('质量评分') || title.toLowerCase().includes('quality');
    const rawScore = item.score ?? item.quality_score ?? item.qualityScore ?? item.rating;
    const rawNeedsReview = item.needs_review ?? (typeof item.quality === 'object' && item.quality ? (item.quality as Record<string, unknown>).needs_review : undefined);
    if (!hasQualityTitle && rawScore === undefined) continue;

    const searchText = [
      title,
      stringifyUnknown(item.summary),
      stringifyUnknown(item.note),
      stringifyUnknown(item.notes),
      stringifyUnknown(item.content),
      stringifyUnknown(item.description)
    ].filter(Boolean).join(' ');
    const score = normalizeQualityScore(rawScore) ?? scoreFromText(searchText);
    const note = stringifyUnknown(item.note ?? item.notes ?? item.summary ?? item.content ?? item.description);
    const needsReview = rawNeedsReview === true || rawNeedsReview === 'true' || (typeof score === 'number' && score < 70);
    return { title: title || '质量评分', score, note, needsReview };
  }
  return null;
}

function stringifyUnknown(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  if (Array.isArray(value)) return value.map(stringifyUnknown).filter(Boolean).join(' ');
  return '';
}

function normalizeQualityScore(value: unknown): number | null {
  const raw = typeof value === 'number' ? value : typeof value === 'string' ? Number(value.match(/-?\d+(?:\.\d+)?/)?.[0]) : NaN;
  if (!Number.isFinite(raw)) return null;
  const normalized = raw <= 1 ? raw * 100 : raw <= 10 ? raw * 10 : raw;
  return Math.max(0, Math.min(100, Math.round(normalized)));
}

function scoreFromText(text: string): number | null {
  const ratio = /(\d+(?:\.\d+)?)\s*\/\s*(100|10)/.exec(text);
  if (ratio) return normalizeQualityScore(Number(ratio[1]) / Number(ratio[2]));
  const percent = /(\d+(?:\.\d+)?)\s*%/.exec(text);
  if (percent) return normalizeQualityScore(Number(percent[1]));
  return null;
}

function QualityScorePanel({ quality, onReview, disabled }: { quality: QualityScore; onReview?: () => void; disabled?: boolean }) {
  const hasScore = typeof quality.score === 'number';
  const score = hasScore ? quality.score ?? 0 : 0;
  const lowScore = quality.needsReview || (hasScore && score < 70);
  const label = lowScore ? '需要重跑或人工复核' : hasScore ? '质量可用' : '等待人工判断';
  return (
    <div className={lowScore ? 'quality-score-panel quality-score-panel-low' : 'quality-score-panel'}>
      <div className="quality-score-header">
        <div>
          <span>质量评分</span>
          <strong>{hasScore ? `${score}/100` : '未给出数值'}</strong>
        </div>
        <em>{label}</em>
        {onReview && (
          <button type="button" className="quality-review-button" onClick={onReview} disabled={disabled}>
            {disabled ? '正在重新生成' : '重新生成深度解析'}
          </button>
        )}
      </div>
      <div className="quality-score-track" aria-label={hasScore ? `质量评分 ${score}/100` : '质量评分未给出数值'}>
        <span style={{ width: `${hasScore ? score : 0}%` }} />
      </div>
      {quality.note && <p>{quality.note}</p>}
    </div>
  );
}

function metadataFormFromPaper(paper: Paper): PaperMetadataForm {
  return {
    title: paper.title,
    authors: paper.authors.join('\n'),
    publication_type: paper.publication_type,
    year: paper.year ? String(paper.year) : '',
    venue: paper.venue,
    volume: paper.volume,
    issue: paper.issue,
    pages: paper.pages,
    area: paper.area,
    abstract: paper.abstract,
    doi: paper.doi,
    arxiv_id: paper.arxiv_id,
    source_url: paper.source_url,
    code_status: paper.code_status,
    keywords: paper.keywords.join(', ')
  };
}

function paperPatchFromMetadataForm(form: PaperMetadataForm) {
  return {
    title: form.title.trim(),
    authors: form.authors
      .split(/[\n,;，；]+/)
      .map((item) => item.trim())
      .filter(Boolean),
    publication_type: form.publication_type,
    year: form.year.trim() ? Number(form.year) : null,
    venue: form.venue.trim(),
    volume: form.volume.trim(),
    issue: form.issue.trim(),
    pages: form.pages.trim(),
    area: form.area.trim(),
    abstract: form.abstract.trim(),
    doi: form.doi.trim(),
    arxiv_id: form.arxiv_id.trim(),
    source_url: form.source_url.trim(),
    code_status: form.code_status,
    keywords: splitKeywords(form.keywords)
  };
}

function mergeMetadataCandidate(form: PaperMetadataForm, candidate: PaperMetadataCandidate | null | undefined): PaperMetadataForm {
  if (!candidate) return form;
  return {
    ...form,
    title: candidate.title ? String(candidate.title) : form.title,
    authors: Array.isArray(candidate.authors) && candidate.authors.length ? candidate.authors.join('\n') : form.authors,
    year: candidate.year ? String(candidate.year) : form.year,
    venue: candidate.venue ? String(candidate.venue) : form.venue,
    abstract: candidate.abstract ? String(candidate.abstract) : form.abstract,
    doi: candidate.doi ? String(candidate.doi) : form.doi,
    arxiv_id: candidate.arxiv_id ? String(candidate.arxiv_id) : form.arxiv_id,
    source_url: candidate.source_url ? String(candidate.source_url) : form.source_url,
    keywords: Array.isArray(candidate.keywords) && candidate.keywords.length ? candidate.keywords.join(', ') : form.keywords
  };
}

function formatAuthors(authors: string[]) {
  if (authors.length === 0) return '作者待补';
  if (authors.length <= 4) return authors.join('、');
  return `${authors.slice(0, 4).join('、')} 等`;
}

function paperSource(paper: Paper) {
  return [paper.venue || paper.area || '来源待补', paper.year ?? '年份待补'].filter(Boolean).join(' / ');
}

function escapeBibTeX(value: string) {
  return value.replace(/[{}]/g, '').replace(/\\/g, '\\textbackslash{}');
}

function risTypeFor(paper: Paper) {
  if (paper.publication_type === 'conference') return 'CPAPER';
  if (paper.publication_type === 'preprint') return 'RPRT';
  if (paper.publication_type === 'thesis') return 'THES';
  if (paper.publication_type === 'report') return 'RPRT';
  return 'JOUR';
}

function bibTypeFor(paper: Paper) {
  if (paper.publication_type === 'conference') return 'inproceedings';
  if (paper.publication_type === 'thesis') return 'phdthesis';
  if (paper.publication_type === 'report') return 'techreport';
  if (paper.publication_type === 'preprint') return 'misc';
  return 'article';
}

function buildRis(papers: Paper[]) {
  return papers
    .map((paper) => {
      const lines = [`TY  - ${risTypeFor(paper)}`, `TI  - ${paper.title}`];
      paper.authors.forEach((author) => lines.push(`AU  - ${author}`));
      if (paper.year) lines.push(`PY  - ${paper.year}`);
      if (paper.venue) lines.push(`JO  - ${paper.venue}`);
      if (paper.volume) lines.push(`VL  - ${paper.volume}`);
      if (paper.issue) lines.push(`IS  - ${paper.issue}`);
      if (paper.pages) lines.push(`SP  - ${paper.pages}`);
      if (paper.doi) lines.push(`DO  - ${paper.doi}`);
      if (paper.source_url) lines.push(`UR  - ${paper.source_url}`);
      else if (paper.arxiv_id) lines.push(`UR  - ${arxivUrl(paper.arxiv_id)}`);
      if (paper.abstract) lines.push(`AB  - ${paper.abstract}`);
      paper.keywords.forEach((keyword) => lines.push(`KW  - ${keyword}`));
      lines.push('ER  -');
      return lines.join('\n');
    })
    .join('\n\n');
}

function buildBibTeX(papers: Paper[]) {
  return papers
    .map((paper) => {
      const key = `researchos${paper.id}`;
      const fields = [`  title = {${escapeBibTeX(paper.title)}}`];
      if (paper.authors.length) fields.push(`  author = {${paper.authors.map(escapeBibTeX).join(' and ')}}`);
      if (paper.year) fields.push(`  year = {${paper.year}}`);
      if (paper.venue) {
        fields.push(
          paper.publication_type === 'conference'
            ? `  booktitle = {${escapeBibTeX(paper.venue)}}`
            : `  journal = {${escapeBibTeX(paper.venue)}}`
        );
      }
      if (paper.volume) fields.push(`  volume = {${escapeBibTeX(paper.volume)}}`);
      if (paper.issue) fields.push(`  number = {${escapeBibTeX(paper.issue)}}`);
      if (paper.pages) fields.push(`  pages = {${escapeBibTeX(paper.pages)}}`);
      if (paper.doi) fields.push(`  doi = {${escapeBibTeX(paper.doi)}}`);
      if (paper.source_url) fields.push(`  url = {${escapeBibTeX(paper.source_url)}}`);
      else if (paper.arxiv_id) fields.push(`  url = {${escapeBibTeX(arxivUrl(paper.arxiv_id))}}`);
      if (paper.keywords.length) fields.push(`  keywords = {${paper.keywords.map(escapeBibTeX).join(', ')}}`);
      return `@${bibTypeFor(paper)}{${key},\n${fields.join(',\n')}\n}`;
    })
    .join('\n\n');
}

function downloadText(filename: string, content: string, type: string) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function paperCode(paperOrId: Paper | number) {
  if (typeof paperOrId !== 'number' && paperOrId.code) return paperOrId.code;
  const id = typeof paperOrId === 'number' ? paperOrId : paperOrId.id;
  return `P${String(id).padStart(6, '0')}`;
}

function docCode(docOrId: Doc | number) {
  if (typeof docOrId !== 'number' && docOrId.code) return docOrId.code;
  const id = typeof docOrId === 'number' ? docOrId : docOrId.id;
  return `D${String(id).padStart(6, '0')}`;
}

function compactTitle(value: string, maxLength = 24) {
  const normalized = value.trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, maxLength)}…`;
}

function parsePaperCodeInput(value: string) {
  return Array.from(
    new Set(
      value
        .split(/[\s,，;；]+/)
        .map((item) => item.trim().replace(/^P/i, ''))
        .map((item) => item.replace(/^0+/, '') || '0')
        .filter((item) => /^\d+$/.test(item))
        .map(Number)
        .filter((item) => item > 0)
    )
  );
}

function SelectedPaperPanel({
  papers,
  onRemove,
  onClear,
  emptyText = '还没有勾选论文'
}: {
  papers: Paper[];
  onRemove: (paperId: number) => void;
  onClear: () => void;
  emptyText?: string;
}) {
  return (
    <details className="selected-paper-panel" open>
      <summary>
        <span>已勾选论文</span>
        <strong>{papers.length} 篇</strong>
      </summary>
      {papers.length === 0 ? (
        <p>{emptyText}</p>
      ) : (
        <>
          <div className="selected-paper-list" aria-label="已勾选论文">
            {papers.map((paper) => (
              <span className="selected-paper-chip" key={paper.id} title={`${paperCode(paper)} ${paper.title}`}>
                <b>{paperCode(paper)}</b>
                <em>{compactTitle(paper.title)}</em>
                <button type="button" aria-label={`移除 ${paper.title}`} onClick={() => onRemove(paper.id)}>
                  ×
                </button>
              </span>
            ))}
          </div>
          <button type="button" className="text-button" onClick={onClear}>
            清空已选
          </button>
        </>
      )}
    </details>
  );
}

function PaperLibrary() {
  const [reloadToken, setReloadToken] = useState(0);
  const [draftQuery, setDraftQuery] = useState('');
  const [draftStatus, setDraftStatus] = useState('all');
  const [draftYear, setDraftYear] = useState('all');
  const [draftReadingStatus, setDraftReadingStatus] = useState('all');
  const [draftReproductionStatus, setDraftReproductionStatus] = useState('all');
  const [draftKeywordSearch, setDraftKeywordSearch] = useState('');
  const [selectedKeywords, setSelectedKeywords] = useState<string[]>([]);
  const [appliedFilters, setAppliedFilters] = useState({
    query: '',
    status: 'all',
    year: 'all',
    readingStatus: 'all',
    reproductionStatus: 'all',
    keywords: [] as string[],
    page: 1,
    pageSize: 25
  });
  const searchUrl = useMemo(
    () =>
      buildPaperSearchUrl({
        query: appliedFilters.query,
        status: appliedFilters.status,
        year: appliedFilters.year,
        readingStatus: appliedFilters.readingStatus,
        reproductionStatus: appliedFilters.reproductionStatus,
        keywords: appliedFilters.keywords,
        page: appliedFilters.page,
        pageSize: appliedFilters.pageSize,
        reloadToken
      }),
    [appliedFilters, reloadToken]
  );
  const suggestUrl = useMemo(
    () => `/api/keywords/suggest/?q=${encodeURIComponent(draftKeywordSearch.trim())}`,
    [draftKeywordSearch]
  );
  const { data: searchData, loading, error } = useApiData<PaperSearchResponse>(searchUrl, emptyPaperSearch);
  const { data: keywordSuggestions } = useApiData<KeywordSuggestion[]>(suggestUrl, []);
  const [selectedPapers, setSelectedPapers] = useState<Map<number, Paper>>(() => new Map());
  const [processingId, setProcessingId] = useState<number | null>(null);
  const [actionMessage, setActionMessage] = useState('');
  const [actionError, setActionError] = useState('');

  const papers = searchData.results;
  const visibleKeywordSuggestions = (draftKeywordSearch.trim() ? keywordSuggestions : searchData.hot_keywords)
    .filter((keyword) => keyword.paper_count > 0)
    .slice(0, 10);
  const selectedPaperList = useMemo(() => Array.from(selectedPapers.values()), [selectedPapers]);
  const selectedPdfCount = selectedPaperList.filter((paper) => paper.has_pdf).length;
  const allPageSelected = papers.length > 0 && papers.every((paper) => selectedPapers.has(paper.id));

  const addKeyword = (keyword: string) => {
    setSelectedKeywords((current) => {
      if (current.some((item) => item.toLowerCase() === keyword.toLowerCase())) return current;
      return [...current, keyword];
    });
    setDraftKeywordSearch('');
  };

  const removeKeyword = (keyword: string) => {
    setSelectedKeywords((current) => current.filter((item) => item.toLowerCase() !== keyword.toLowerCase()));
  };

  const applySearch = () => {
    setAppliedFilters({
      query: draftQuery.trim(),
      status: draftStatus,
      year: draftYear,
      readingStatus: draftReadingStatus,
      reproductionStatus: draftReproductionStatus,
      keywords: selectedKeywords,
      page: 1,
      pageSize: appliedFilters.pageSize
    });
    setActionMessage('');
    setActionError('');
  };

  const resetSearch = () => {
    setDraftQuery('');
    setDraftStatus('all');
    setDraftYear('all');
    setDraftReadingStatus('all');
    setDraftReproductionStatus('all');
    setDraftKeywordSearch('');
    setSelectedKeywords([]);
    setAppliedFilters({
      query: '',
      status: 'all',
      year: 'all',
      readingStatus: 'all',
      reproductionStatus: 'all',
      keywords: [],
      page: 1,
      pageSize: appliedFilters.pageSize
    });
  };

  const togglePaperSelection = (paperId: number) => {
    const paper = papers.find((item) => item.id === paperId);
    if (!paper) return;
    setSelectedPapers((current) => {
      const next = new Map(current);
      if (next.has(paperId)) next.delete(paperId);
      else next.set(paperId, paper);
      return next;
    });
  };

  const toggleAllPage = () => {
    setSelectedPapers((current) => {
      const next = new Map(current);
      if (allPageSelected) {
        papers.forEach((paper) => next.delete(paper.id));
      } else {
        papers.forEach((paper) => next.set(paper.id, paper));
      }
      return next;
    });
  };

  const removeSelectedPaper = (paperId: number) => {
    setSelectedPapers((current) => {
      const next = new Map(current);
      next.delete(paperId);
      return next;
    });
  };

  const clearSelectedPapers = () => {
    setSelectedPapers(new Map());
  };

  const changePage = (page: number) => {
    setAppliedFilters((current) => ({ ...current, page: Math.max(1, Math.min(searchData.total_pages, page)) }));
  };

  const changePageSize = (pageSize: number) => {
    setAppliedFilters((current) => ({ ...current, page: 1, pageSize }));
  };

  const exportRis = () => downloadText('research-os-papers.ris', buildRis(selectedPaperList), 'application/x-research-info-systems');
  const exportBibTeX = () => downloadText('research-os-papers.bib', buildBibTeX(selectedPaperList), 'application/x-bibtex');
  const exportPdfs = () => {
    selectedPaperList
      .filter((paper) => paper.has_pdf)
      .forEach((paper) => {
        const link = document.createElement('a');
        link.href = `/api/papers/${paper.id}/pdf/?download=1`;
        link.download = `${paper.slug || `paper-${paper.id}`}.pdf`;
        document.body.appendChild(link);
        link.click();
        link.remove();
      });
  };
  const runLightProcess = async (paper: Paper) => {
    setProcessingId(paper.id);
    setActionMessage('');
    setActionError('');
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/light-process/`, { method: 'POST' });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '轻量处理失败。'));
      const taskId = payload && typeof payload === 'object' && 'task' in payload ? (payload.task as TaskItem).id : null;
      setActionMessage(`《${payload.paper.title}》已加入轻量处理队列${taskId ? `（任务 T${String(taskId).padStart(4, '0')}）` : ''}。可以在任务队列页查看进度。`);
      setReloadToken((value) => value + 1);
    } catch (processError) {
      setActionError(processError instanceof Error ? processError.message : '轻量处理失败。');
    } finally {
      setProcessingId(null);
    }
  };

  return (
    <main className="page">
      <Header
        eyebrow="Research Library"
        title="论文库"
        description="按年份、主题词、处理状态与自由文本筛选论文，支持稳定分页浏览与批量导出。"
      />
      <section className="paper-search-panel">
        <div className="filter-block">
          <label>年份</label>
          <div className="segmented">
            <button className={draftYear === 'all' ? 'active' : ''} type="button" onClick={() => setDraftYear('all')}>
              全部
            </button>
            {searchData.years.map((item) => (
              <button className={draftYear === String(item) ? 'active' : ''} type="button" key={item} onClick={() => setDraftYear(String(item))}>
                {item}
              </button>
            ))}
            {searchData.years.length === 0 && <span className="muted-inline">入库后会自动出现年份按钮</span>}
          </div>
        </div>

        <div className="paper-search-main">
          <label>
            <span>模糊搜索</span>
            <input
              value={draftQuery}
              onChange={(event) => setDraftQuery(event.target.value)}
              placeholder="输入题名、作者、摘要或主题词"
            />
          </label>
          <label>
            <span>处理状态</span>
            <select value={draftStatus} onChange={(event) => setDraftStatus(event.target.value)}>
              <option value="all">全部状态</option>
              <option value="uploaded">已上传</option>
              <option value="light_ready">概览完成</option>
              <option value="deep_ready">深度完成</option>
              <option value="needs_review">待审核</option>
              <option value="archived">已归档</option>
            </select>
          </label>
          <label>
            <span>阅读状态</span>
            <select value={draftReadingStatus} onChange={(event) => setDraftReadingStatus(event.target.value)}>
              <option value="all">全部阅读状态</option>
              <option value="unread">未读</option>
              <option value="skimmed">已粗读</option>
              <option value="deep_reading">深读中</option>
              <option value="discussed">已讨论</option>
              <option value="adopted">已采用</option>
              <option value="rejected">已排除</option>
            </select>
          </label>
          <label>
            <span>复现状态</span>
            <select value={draftReproductionStatus} onChange={(event) => setDraftReproductionStatus(event.target.value)}>
              <option value="all">全部复现状态</option>
              <option value="unknown">未知</option>
              <option value="not_applicable">不适用</option>
              <option value="planned">已计划</option>
              <option value="in_progress">进行中</option>
              <option value="reproduced">已复现</option>
              <option value="failed">复现失败</option>
            </select>
          </label>
          <div className="search-command-group">
            <button type="button" onClick={applySearch}>
              开始搜索
            </button>
            <button type="button" className="secondary-button" onClick={resetSearch}>
              重置条件
            </button>
          </div>
        </div>

        <div className="keyword-picker">
          <div className="section-heading">
            <div>
              <span>精确关键词</span>
            </div>
            <button type="button" className="secondary-button" disabled={selectedKeywords.length === 0} onClick={() => setSelectedKeywords([])}>
              清空关键词
            </button>
          </div>
          <div className="keyword-input-row">
            <input
              value={draftKeywordSearch}
              onChange={(event) => setDraftKeywordSearch(event.target.value)}
              placeholder="输入主题词精确筛选；下方显示热门主题，也可继续输入自动补全"
            />
          </div>
          {selectedKeywords.length > 0 && (
            <div className="selected-keyword-strip">
              {selectedKeywords.map((keyword) => (
                <button type="button" key={keyword} onClick={() => removeKeyword(keyword)}>
                  {keyword} ×
                </button>
              ))}
            </div>
          )}
          <div className="keyword-suggestion-row">
            {visibleKeywordSuggestions.map((keyword) => (
              <button
                className={selectedKeywords.some((item) => item.toLowerCase() === keyword.name.toLowerCase()) ? 'tag-button active' : 'tag-button'}
                key={keyword.name}
                type="button"
                onClick={() => addKeyword(keyword.name)}
              >
                {keyword.name}
                <small>{keyword.paper_count}</small>
              </button>
            ))}
            {!draftKeywordSearch.trim() && searchData.hot_keywords.length === 0 && (
              <span className="muted-inline">入库后会显示热门主题词</span>
            )}
          </div>
        </div>
      </section>

      {searchData.related_keywords.length > 0 && (
        <section className="related-keyword-panel">
          <span>本次搜索关联到的主题词</span>
          <div className="tag-cloud tag-cloud-compact">
            {searchData.related_keywords.map((keyword) => (
              <button type="button" className="tag-button" key={keyword.name} onClick={() => addKeyword(keyword.name)}>
                {keyword.name}
              </button>
            ))}
          </div>
        </section>
      )}

      <section className="result-toolbar">
        <div className="result-actions">
          <label className="select-all-control">
            <input
              type="checkbox"
              checked={allPageSelected}
              disabled={papers.length === 0}
              onChange={toggleAllPage}
            />
            全选当前页
          </label>
          <select value={appliedFilters.pageSize} onChange={(event) => changePageSize(Number(event.target.value))}>
            <option value={25}>每页 25</option>
            <option value={50}>每页 50</option>
            <option value={100}>每页 100</option>
          </select>
          <div className="result-meta result-meta-inline">
            <strong>共 {searchData.count} 篇</strong>
            <span>第 {searchData.page} / {searchData.total_pages} 页，已选 {selectedPaperList.length} 篇</span>
          </div>
          <div className="export-group" aria-label="导出已勾选论文">
            <button type="button" className="secondary-button" disabled={selectedPaperList.length === 0} onClick={exportRis}>
              导出 RIS
            </button>
            <button type="button" className="secondary-button" disabled={selectedPdfCount === 0} onClick={exportPdfs}>
              导出 PDF
            </button>
            <button type="button" className="secondary-button" disabled={selectedPaperList.length === 0} onClick={exportBibTeX}>
              导出 BibTeX
            </button>
          </div>
        </div>
      </section>

      {selectedPaperList.length > 0 && (
        <SelectedPaperPanel
          papers={selectedPaperList}
          onRemove={removeSelectedPaper}
          onClear={clearSelectedPapers}
          emptyText="勾选论文后，这里会保留编号和短标题；切换搜索条件不会丢失已选范围。"
        />
      )}

      {(actionMessage || actionError) && (
        <div className={actionError ? 'form-message form-message-error paper-action-message' : 'form-message paper-action-message'}>
          {actionError || actionMessage}
        </div>
      )}
      {loading ? (
        <EmptyState title="正在加载论文库" note="系统正在读取论文元数据、关键词和处理状态。" />
      ) : error ? (
        <EmptyState title="论文库暂时不可用" note="目录接口未返回有效数据，请检查服务状态。" />
      ) : papers.length === 0 ? (
        <EmptyState title="没有匹配的论文" note="可放宽年份、关键词或模糊搜索条件；新论文入库后会自动出现在这里。" />
      ) : (
        <section className="table-panel">
          {papers.map((paper) => (
            <article className="row-card row-card-rich" key={paper.id}>
              <label className="paper-select-control" aria-label={`选择 ${paper.title}`}>
                <input
                  type="checkbox"
                  checked={selectedPapers.has(paper.id)}
                  onChange={() => togglePaperSelection(paper.id)}
                />
              </label>
              <div>
                <div className="paper-title-row">
                  <span className="paper-code">{paperCode(paper)}</span>
                  <Link className="paper-title-link" to={`/papers/${paper.id}`}>
                    {paper.title}
                  </Link>
                </div>
                <p>
                  {paper.year ?? '年份待补'} / {paper.venue || paper.area || '来源待补'} / 更新 {formatDate(paper.updated_at)}
                </p>
                {paper.authors.length > 0 && <p>{formatAuthors(paper.authors)}</p>}
                {paper.keywords.length > 0 && (
                  <div className="mini-tags">
                    {paper.keywords.slice(0, 6).map((keyword) => (
                      <span key={keyword}>{keyword}</span>
                    ))}
                  </div>
                )}
              </div>
              <div className="row-actions">
                <StatusPill value={paper.status} />
                {paper.light_profile && <span className="muted-inline">已有概览</span>}
                <Link className="secondary-button link-button" to={`/papers/${paper.id}`}>
                  查看详情
                </Link>
                {(paper.status === 'uploaded' || paper.status === 'failed') && (
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={processingId === paper.id}
                    onClick={() => runLightProcess(paper)}
                  >
                    {processingId === paper.id ? '处理中' : '轻量处理'}
                  </button>
                )}
              </div>
            </article>
          ))}
        </section>
      )}

      <section className="pagination-bar">
        <button type="button" className="secondary-button" disabled={searchData.page <= 1} onClick={() => changePage(searchData.page - 1)}>
          上一页
        </button>
        <span>第 {searchData.page} 页 / 共 {searchData.total_pages} 页</span>
        <button
          type="button"
          className="secondary-button"
          disabled={searchData.page >= searchData.total_pages}
          onClick={() => changePage(searchData.page + 1)}
        >
          下一页
        </button>
      </section>

    </main>
  );
}

function PaperDetail() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [reloadToken, setReloadToken] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [deepProcessing, setDeepProcessing] = useState(false);
  const [deletingPaper, setDeletingPaper] = useState(false);
  const [deepGuidance, setDeepGuidance] = useState('');
  const [deepTask, setDeepTask] = useState<TaskItem | null>(null);
  const [deepProfiles, setDeepProfiles] = useState<PaperDeepProfile[]>([]);
  const [deepProfilesError, setDeepProfilesError] = useState('');
  const [activatingDeepProfile, setActivatingDeepProfile] = useState<number | null>(null);
  const [deletingDeepProfile, setDeletingDeepProfile] = useState<number | null>(null);
  const [activeTab, setActiveTab] = useState<'overview' | 'pdf' | 'qa'>('overview');
  const [metadataEditing, setMetadataEditing] = useState(false);
  const [metadataForm, setMetadataForm] = useState<PaperMetadataForm | null>(null);
  const [metadataSaving, setMetadataSaving] = useState(false);
  const [suggestionLoading, setSuggestionLoading] = useState(false);
  const [metadataSuggestion, setMetadataSuggestion] = useState<PaperMetadataSuggestion | null>(null);
  const [selectedMetadataCandidate, setSelectedMetadataCandidate] = useState(0);
  const [referenceContent, setReferenceContent] = useState('');
  const [referenceLoading, setReferenceLoading] = useState(false);
  const [referenceCandidates, setReferenceCandidates] = useState<PaperMetadataCandidate[]>([]);
  const [selectedReferenceCandidate, setSelectedReferenceCandidate] = useState(0);
  const [qaHistory, setQaHistory] = useState<PaperQaHistoryItem[]>([]);
  const [qaHistoryError, setQaHistoryError] = useState('');
  const [qaQuestion, setQaQuestion] = useState('');
  const [qaMode, setQaMode] = useState<'compressed' | 'preview'>('compressed');
  const [qaAnswer, setQaAnswer] = useState<PaperQaResponse | null>(null);
  const [qaLoading, setQaLoading] = useState(false);
  const [qaError, setQaError] = useState('');
  const [actionMessage, setActionMessage] = useState('');
  const [actionError, setActionError] = useState('');
  const { data: paper, loading, error } = useApiData<Paper | null>(
    id ? `/api/papers/${id}/?reload=${reloadToken}` : '/api/papers/0/',
    null
  );

  useEffect(() => {
      if (!paper) {
        setMetadataForm(null);
        setMetadataEditing(false);
        return;
      }
      setMetadataForm(metadataFormFromPaper(paper));
      setMetadataEditing(false);
  }, [paper?.id, paper?.updated_at]);

  useEffect(() => {
    let mounted = true;
    if (!paper) {
      setQaHistory([]);
      setQaHistoryError('');
      return () => {
        mounted = false;
      };
    }
    apiFetch(`/api/qa/papers/${paper.id}/history/?reload=${reloadToken}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload: PaperQaHistoryResponse) => {
        if (!mounted) return;
        setQaHistory(payload.results ?? []);
        setQaHistoryError('');
      })
      .catch(() => {
        if (!mounted) return;
        setQaHistory([]);
        setQaHistoryError('问答记录暂时无法读取。');
      });
    return () => {
      mounted = false;
    };
  }, [paper?.id, reloadToken]);

  useEffect(() => {
    let mounted = true;
    if (!paper) {
      setDeepProfiles([]);
      setDeepProfilesError('');
      return () => {
        mounted = false;
      };
    }
    setDeepProfilesError('');
    apiFetch(`/api/papers/${paper.id}/deep-profiles/?reload=${reloadToken}`)
      .then((response) => {
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return response.json();
      })
      .then((payload: PaperDeepProfileListResponse) => {
        if (!mounted) return;
        setDeepProfiles(payload.results ?? []);
        setDeepProfilesError('');
      })
      .catch(() => {
        if (!mounted) return;
        setDeepProfiles([]);
        setDeepProfilesError('Deep profile versions failed to load.');
      });
    return () => {
      mounted = false;
    };
  }, [paper?.id, reloadToken]);

  useEffect(() => {
    if (!paper?.active_deep_task) return;
    const activeTask = paper.active_deep_task;
    setDeepTask((current) => {
      if (current && current.id === activeTask.id && current.status === activeTask.status) {
        return current;
      }
      return activeTask;
    });
    if (activeTask.status === 'pending' || activeTask.status === 'running') {
      setDeepProcessing(true);
    }
  }, [paper?.active_deep_task?.id, paper?.active_deep_task?.status, paper?.active_deep_task?.progress]);

  useEffect(() => {
    if (!deepTask || deepTask.status === 'success' || deepTask.status === 'failed') return;
    const taskId = deepTask.id;
    let cancelled = false;
    let timer: number | undefined;

    async function pollDeepTask() {
      try {
        const response = await apiFetch(`/api/tasks/status/?ids=${taskId}`);
        const payload = (await readResponsePayload(response)) as TaskStatusResponse;
        if (!response.ok) throw new Error(payloadMessage(payload, '深度处理状态读取失败。'));
        if (cancelled) return;
        const nextTask = payload.tasks[0];
        if (!nextTask) return;
        setDeepTask(nextTask);
        if (nextTask.status === 'success') {
          setDeepProcessing(false);
          setActionMessage('深度解析结果已生成。');
          setReloadToken((value) => value + 1);
          return;
        }
        if (nextTask.status === 'failed') {
          setDeepProcessing(false);
          setActionError(nextTask.error || '深度处理任务失败。');
          setReloadToken((value) => value + 1);
          return;
        }
        timer = window.setTimeout(pollDeepTask, payload.next_poll_after_ms || 2500);
      } catch (taskError) {
        if (cancelled) return;
        setActionError(taskError instanceof Error ? taskError.message : '深度处理状态读取失败。');
        setDeepProcessing(false);
      }
    }

    timer = window.setTimeout(pollDeepTask, 800);
    return () => {
      cancelled = true;
      if (timer) window.clearTimeout(timer);
    };
  }, [deepTask?.id, deepTask?.status]);

  const runLightProcess = async (useAi = false) => {
    if (!paper) return;
    setProcessing(true);
    setActionMessage('');
    setActionError('');
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/light-process/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ use_ai: useAi })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '轻量处理失败。'));
      const taskId = payload && typeof payload === 'object' && 'task' in payload ? (payload.task as TaskItem).id : null;
      setActionMessage(`${useAi ? 'AI 轻量概览' : '轻量概览'}已加入任务队列${taskId ? `（任务 T${String(taskId).padStart(4, '0')}）` : ''}。处理完成后刷新页面即可看到结果。`);
      setReloadToken((value) => value + 1);
    } catch (processError) {
      setActionError(processError instanceof Error ? processError.message : '轻量处理失败。');
    } finally {
      setProcessing(false);
    }
  };

  const runDeepProcess = async () => {
    if (!paper) return;
    setDeepProcessing(true);
    setActionMessage('');
    setActionError('');
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/trigger-deep-process/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ guidance: deepGuidance.trim() })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '深度处理任务提交失败。'));
      const task = payload && typeof payload === 'object' && 'task' in payload ? (payload.task as TaskItem) : null;
      if (task) setDeepTask(task);
      setActionMessage(`深度解析已加入重型任务队列${task ? `（任务 T${String(task.id).padStart(4, '0')}）` : ''}。系统将从 PDF 文本生成结构化细读结果。`);
      setReloadToken((value) => value + 1);
    } catch (processError) {
      setActionError(processError instanceof Error ? processError.message : '深度处理任务提交失败。');
    } finally {
      setDeepProcessing(false);
    }
  };

  const deletePaper = async () => {
    if (!paper) return;
    const confirmed = window.confirm(
      `确认删除论文「${paper.title}」吗？\n\n该操作会同时清理 PDF 文件、轻量解读、深度解析、问答记录、相关任务和不再使用的关键词，并释放论文编号。删除后不可恢复。`
    );
    if (!confirmed) return;
    setDeletingPaper(true);
    setActionMessage('');
    setActionError('');
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/`, { method: 'DELETE' });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '删除论文失败。'));
      navigate('/papers');
    } catch (deleteError) {
      setActionError(deleteError instanceof Error ? deleteError.message : '删除论文失败。');
    } finally {
      setDeletingPaper(false);
    }
  };

  const activateDeepProfile = async (profileId: number) => {
    if (!paper) return;
    setActivatingDeepProfile(profileId);
    setActionMessage('');
    setActionError('');
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/deep-profiles/${profileId}/activate/`, { method: 'POST' });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '深度版本切换失败。'));
      const list = payload as PaperDeepProfileListResponse;
      setDeepProfiles(list.results ?? []);
      if (list.active) {
        setDeepProfiles((profiles) => profiles.map((profile) => ({ ...profile, is_active: profile.id === list.active?.id })));
      }
      setActionMessage('已切换深度处理 active 版本。');
      setReloadToken((value) => value + 1);
    } catch (activationError) {
      setActionError(activationError instanceof Error ? activationError.message : '深度版本切换失败。');
    } finally {
      setActivatingDeepProfile(null);
    }
  };

  const deleteDeepProfile = async (profileId: number) => {
    if (!paper) return;
    if (!window.confirm('确定删除这个深度解析版本吗？删除后剩余版本会重新编号。')) return;
    setDeletingDeepProfile(profileId);
    setActionMessage('');
    setActionError('');
    setDeepProfilesError('');
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/deep-profiles/${profileId}/`, { method: 'DELETE' });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '删除深度版本失败。'));
      const list = payload as PaperDeepProfileListResponse;
      setDeepProfiles(list.results ?? []);
      setActionMessage('已删除深度解析版本，并重新编号。');
      setReloadToken((value) => value + 1);
    } catch (deleteError) {
      const message = deleteError instanceof Error ? deleteError.message : '删除深度版本失败。';
      setActionError(message);
      setDeepProfilesError(message);
    } finally {
      setDeletingDeepProfile(null);
    }
  };

  const updateMetadataField = (field: keyof PaperMetadataForm, value: string) => {
    setMetadataForm((current) => (current ? { ...current, [field]: value } : current));
  };

  const saveMetadata = async () => {
    if (!paper || !metadataForm) return;
    setMetadataSaving(true);
    setActionMessage('');
    setActionError('');
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(paperPatchFromMetadataForm(metadataForm))
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '论文元数据保存失败。'));
      setActionMessage('论文元数据已保存。');
      setMetadataEditing(false);
      setReloadToken((value) => value + 1);
    } catch (metadataError) {
      setActionError(metadataError instanceof Error ? metadataError.message : '论文元数据保存失败。');
    } finally {
      setMetadataSaving(false);
    }
  };

  const requestMetadataSuggestion = async () => {
    if (!paper) return;
    setSuggestionLoading(true);
    setActionMessage('');
    setActionError('');
    setMetadataSuggestion(null);
    setSelectedMetadataCandidate(0);
    try {
      const response = await apiFetch(`/api/papers/${paper.id}/metadata-suggestion/`, { method: 'POST' });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, 'AI + web-search 元数据补全暂时不可用。'));
      const suggestionPayload = payload as PaperMetadataSuggestion;
      setMetadataSuggestion(suggestionPayload);
      setSelectedMetadataCandidate((suggestionPayload.candidates ?? []).length > 0 ? 0 : -1);
      setActionMessage('已生成元数据补全建议，请检查后再应用。');
    } catch (suggestionError) {
      setActionError(suggestionError instanceof Error ? suggestionError.message : 'AI + web-search 元数据补全暂时不可用。');
    } finally {
      setSuggestionLoading(false);
    }
  };

  const applyMetadataSuggestion = () => {
    if (!metadataSuggestion) return;
    const suggestion = metadataSuggestion.suggestions ?? {};
    const candidate = metadataSuggestion.candidates?.[selectedMetadataCandidate] ?? null;
    setMetadataForm((current) => {
      if (!current) return current;
      return mergeMetadataCandidate({
        ...current,
        title: suggestion.title ? String(suggestion.title) : current.title,
        authors: Array.isArray(suggestion.authors) && suggestion.authors.length ? suggestion.authors.join('\n') : current.authors,
        year: suggestion.year ? String(suggestion.year) : current.year,
        venue: suggestion.venue ? String(suggestion.venue) : current.venue,
        abstract: suggestion.abstract ? String(suggestion.abstract) : current.abstract,
        doi: suggestion.doi ? String(suggestion.doi) : current.doi,
        arxiv_id: suggestion.arxiv_id ? String(suggestion.arxiv_id) : current.arxiv_id,
        source_url: suggestion.source_url ? String(suggestion.source_url) : current.source_url,
        keywords: Array.isArray(suggestion.keywords) && suggestion.keywords.length ? suggestion.keywords.join(', ') : current.keywords
      }, candidate);
    });
  };

  const parseReferenceMetadata = async () => {
    if (!referenceContent.trim()) {
      setActionError('请先粘贴 Zotero / EndNote 导出的 RIS、BibTeX 或参考文献文本。');
      return;
    }
    setReferenceLoading(true);
    setActionMessage('');
    setActionError('');
    try {
      const response = await apiFetch('/api/papers/metadata-reference-candidates/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ content: referenceContent })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '参考文献解析失败。'));
      const parsed = payload as PaperReferenceImportResponse;
      setReferenceCandidates(parsed.candidates ?? []);
      setSelectedReferenceCandidate((parsed.candidates ?? []).length > 0 ? 0 : -1);
      setActionMessage(parsed.count > 0 ? `已解析 ${parsed.count} 条候选元数据。` : '没有从参考文献文本中解析到可用候选。');
    } catch (referenceError) {
      setActionError(referenceError instanceof Error ? referenceError.message : '参考文献解析失败。');
    } finally {
      setReferenceLoading(false);
    }
  };

  const applyReferenceCandidate = () => {
    const candidate = referenceCandidates[selectedReferenceCandidate];
    if (!candidate) return;
    setMetadataForm((current) => (current ? mergeMetadataCandidate(current, candidate) : current));
  };

  const askCurrentPaper = async () => {
    if (!paper) return;
    setQaError('');
    setQaAnswer(null);
    if (!qaQuestion.trim()) {
      setQaError('请先输入问题。');
      return;
    }
    setQaLoading(true);
    try {
      const response = await apiFetch(`/api/qa/papers/${paper.id}/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: qaQuestion.trim(), mode: qaMode })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '当前论文问答失败。'));
      setQaAnswer(payload as PaperQaResponse);
      setQaQuestion('');
      setReloadToken((value) => value + 1);
    } catch (err) {
      setQaError(err instanceof Error ? err.message : '当前论文问答失败。');
    } finally {
      setQaLoading(false);
    }
  };

  if (loading) {
    return (
      <main className="page">
        <EmptyState title="正在加载论文详情" note="正在读取元数据、主题词和解读结果。" />
      </main>
    );
  }

  if (error || !paper) {
    return (
      <main className="page">
        <EmptyState title="论文不存在或暂时不可用" note="可返回论文库重新选择，或检查后端接口状态。" />
      </main>
    );
  }

  const hasLightProfile = Boolean(paper.light_profile);
  const externalLink = safeExternalUrl(paper.source_url) || arxivUrl(paper.arxiv_id);
  const activeDeepProfile = deepProfiles.length > 0 ? deepProfiles.find((profile) => profile.is_active) ?? null : paper.deep_profile;
  const activeQualityScore = extractQualityScore(activeDeepProfile?.code_suggestions);

  return (
    <main className="page">
      <header className="paper-hero">
        <div>
          <p className="eyebrow">论文详情</p>
          <h1>{paper.title}</h1>
          <p className="lede">{formatAuthors(paper.authors)} · {paperSource(paper)}</p>
          <div className="detail-tags">
            <StatusPill value={paper.status} />
            <StatusPill value={paper.code_status || 'missing'} />
            <span>{publicationLabels[paper.publication_type] ?? paper.publication_type}</span>
          </div>
        </div>
        <div className="detail-actions">
          <Link className="secondary-button link-button" to="/papers">
            返回目录
          </Link>
          {paper.has_pdf && (
            <a className="secondary-button link-button" href={`/api/papers/${paper.id}/pdf/?download=1`}>
              导出 PDF
            </a>
          )}
          {!hasLightProfile && (paper.status === 'uploaded' || paper.status === 'failed') && (
            <button type="button" onClick={() => runLightProcess(false)} disabled={processing}>
              {processing ? '处理中' : '生成轻量概览'}
            </button>
          )}
          {paper.has_pdf && (
            <button type="button" onClick={() => runLightProcess(true)} disabled={processing}>
              {processing ? '处理中' : 'AI粗读'}
            </button>
          )}
          {paper.has_pdf && (
            <button type="button" onClick={runDeepProcess} disabled={deepProcessing || paper.status === 'deep_processing'}>
              {deepProcessing || paper.status === 'deep_processing' ? '深度处理中' : 'AI精读'}
            </button>
          )}
          <button type="button" className="danger-button" onClick={deletePaper} disabled={deletingPaper}>
            {deletingPaper ? '删除中' : '删除论文'}
          </button>
        </div>
      </header>
      {paper.has_pdf && (
        <section className="detail-card deep-guidance-card">
          <label>
            细读方向
            <input
              value={deepGuidance}
              onChange={(event) => setDeepGuidance(event.target.value)}
              placeholder="可选，例如：重点关注方法公式和复现实验"
              maxLength={500}
            />
          </label>
        </section>
      )}

      {(actionMessage || actionError) && (
        <div className={actionError ? 'form-message form-message-error paper-action-message' : 'form-message paper-action-message'}>
          {actionError || actionMessage}
        </div>
      )}
      {deepTask && deepTask.status !== 'success' && deepTask.status !== 'failed' && (
        <div className="form-message paper-action-message">
          深度处理任务 T{String(deepTask.id).padStart(4, '0')}：{statusText(deepTask.status)} / {deepTask.stage || 'queued'} / {deepTask.progress}%
        </div>
      )}

      <div className="detail-tabs" role="tablist" aria-label="论文详情标签">
        <button type="button" className={activeTab === 'overview' ? 'active' : ''} onClick={() => setActiveTab('overview')}>概览</button>
        <button type="button" className={activeTab === 'pdf' ? 'active' : ''} onClick={() => setActiveTab('pdf')}>PDF</button>
        <button type="button" className={activeTab === 'qa' ? 'active' : ''} onClick={() => setActiveTab('qa')}>问答</button>
      </div>

      {activeTab === 'overview' && (
      <section className="detail-layout">
        <div className="detail-main">
          <article className="detail-card">
            <div className="panel-title">
              <div>
                <p className="eyebrow">摘要</p>
                <h2>论文摘要</h2>
              </div>
            </div>
            <RichTextBlock
              text={paper.abstract || ''}
              fallback="暂未记录摘要。轻量处理会尽量从 PDF 中提取一段可用文本，深度解析阶段会生成更完整的章节内容。"
            />
          </article>

          <article className="detail-card">
            <div className="panel-title">
              <div>
                <p className="eyebrow">中文概览</p>
                <h2>AI 粗读</h2>
              </div>
              {paper.light_profile?.generator && <span className="muted-inline">{paper.light_profile.generator}</span>}
            </div>
            {paper.light_profile ? (
              <div className="profile-sections">
                <section>
                  <h3>研究背景</h3>
                  <RichTextBlock text={paper.light_profile.background} fallback="背景内容待补。" />
                </section>
                <section>
                  <h3>方法原理</h3>
                  <RichTextBlock text={paper.light_profile.method} fallback="方法内容待补。" />
                </section>
                <section>
                  <h3>主要结果</h3>
                  <RichTextBlock text={paper.light_profile.results} fallback="结果内容待补。" />
                </section>
              </div>
            ) : (
              <EmptyState title="尚未生成 AI 粗读" note="可先生成研究背景、方法原理与主要结果，后续再按需启动 AI 精读。" />
            )}
          </article>

          <article className="detail-card">
            <div className="panel-title">
              <div>
                <p className="eyebrow">深度处理</p>
                <h2>AI 精读</h2>
              </div>
              {activeDeepProfile?.parser_name && <span className="muted-inline">{activeDeepProfile.parser_name}</span>}
            </div>
            {activeDeepProfile ? (
              <div className="profile-sections">
                <section>
                  <h3>结构化摘要</h3>
                  {activeQualityScore && <QualityScorePanel quality={activeQualityScore} onReview={runDeepProcess} disabled={deepProcessing || paper.status === 'deep_processing'} />}
                  {paper.has_pdf && (
                    <div className="deep-guidance-inline">
                      <label>
                        细读方向
                        <input
                          value={deepGuidance}
                          onChange={(event) => setDeepGuidance(event.target.value)}
                          placeholder="可选，例如：重点关注方法公式、复现实验、误差来源或应用边界"
                          maxLength={500}
                        />
                      </label>
                      <button type="button" className="secondary-button" onClick={runDeepProcess} disabled={deepProcessing || paper.status === 'deep_processing'}>
                        {deepProcessing || paper.status === 'deep_processing' ? '正在重新生成' : '重新生成深度解析'}
                      </button>
                    </div>
                  )}
                  <RichTextBlock text={activeDeepProfile.summary} fallback="深度解析摘要待补。" />
                </section>
                <section>
                  <h3>章节 / 图表 / 公式</h3>
                  <p>
                    章节 {activeDeepProfile.sections.length} 个，图表 {activeDeepProfile.figures.length} 个，公式 {activeDeepProfile.formulas.length} 个。
                  </p>
                  {activeDeepProfile.sections.length > 0 && (
                    <div className="deep-section-list">
                      {activeDeepProfile.sections.map((section, index) => {
                        const sectionTitle = String(section.title ?? `Section ${index + 1}`);
                        const sectionSummary = section.summary ? String(section.summary) : '';
                        const sectionConfidence = section.confidence ? String(section.confidence) : '';
                        return (
                          <div className="deep-section-item reading-note-card" key={`${sectionTitle}-${index}`}>
                            <div className="reading-note-heading">
                              <span>阅读笔记 {index + 1}</span>
                              <strong>{sectionTitle}</strong>
                            </div>
                            {sectionSummary && <RichTextBlock text={sectionSummary} fallback="章节内容待补。" />}
                            {sectionConfidence && <small>证据等级：{sectionConfidence}</small>}
                          </div>
                        );
                      })}
                    </div>
                  )}
                </section>
                <section>
                  <h3>复现备注</h3>
                  <RichTextBlock text={activeDeepProfile.reproduction_notes || ''} fallback="\u590d\u73b0\u4fe1\u606f\u4ecd\u9700\u4eba\u5de5\u6838\u5bf9\u3002" />
                </section>
              </div>
            ) : (
              <EmptyState title="尚未生成 AI 精读" note="启动后系统会围绕形式化定义、方法细节、实验结果与局限性生成结构化笔记。" />
            )}
            {deepProfilesError && <p className="inline-error">{deepProfilesError}</p>}
            {deepProfiles.length > 0 && (
              <div className="version-list">
                <h3>深度版本</h3>
                {deepProfiles.map((profile) => (
                  <div
                    className={profile.is_active ? 'version-row active' : 'version-row'}
                    key={profile.id}
                  >
                    <span>v{profile.version}</span>
                    <strong>{profile.parser_name}</strong>
                    <em>{profile.is_active ? '当前版本' : '可切换'}</em>
                    <div className="version-actions">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={profile.is_active || activatingDeepProfile === profile.id || deletingDeepProfile === profile.id}
                        onClick={() => activateDeepProfile(profile.id)}
                      >
                        {activatingDeepProfile === profile.id ? '切换中' : '设为当前'}
                      </button>
                      <button
                        type="button"
                        className="danger-button"
                        disabled={deletingDeepProfile === profile.id || activatingDeepProfile === profile.id}
                        onClick={() => deleteDeepProfile(profile.id)}
                      >
                        {deletingDeepProfile === profile.id ? '删除中' : '删除'}
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </article>

        </div>

        <aside className="detail-side">
          <article className="detail-card">
            <h2>论文元数据</h2>
            <div className="metadata-grid">
              <span>年份</span><strong>{paper.year ?? '待补'}</strong>
              <span>作者</span><strong>{formatAuthors(paper.authors)}</strong>
              <span>来源</span><strong>{paper.venue || paper.area || '待补'}</strong>
              <span>DOI</span><strong>{paper.doi || '待补'}</strong>
              <span>arXiv</span><strong>{paper.arxiv_id || '待补'}</strong>
              <span>更新时间</span><strong>{formatFullDate(paper.updated_at)}</strong>
            </div>
            {externalLink && (
              <a className="secondary-button link-button full-width-link" href={externalLink} target="_blank" rel="noreferrer">
                打开论文来源
              </a>
            )}
            {metadataForm && (
              <button
                type="button"
                className="secondary-button full-width-link"
                onClick={() => setMetadataEditing((value) => !value)}
              >
                {metadataEditing ? '收起元数据编辑' : '编辑元数据'}
              </button>
            )}
            {metadataEditing && metadataForm && (
              <div className="metadata-editor">
                <label>标题<input value={metadataForm.title} onChange={(event) => updateMetadataField('title', event.target.value)} /></label>
                <label>作者<textarea value={metadataForm.authors} onChange={(event) => updateMetadataField('authors', event.target.value)} /></label>
                <div className="metadata-editor-grid">
                  <label>年份<input value={metadataForm.year} onChange={(event) => updateMetadataField('year', event.target.value)} /></label>
                  <label>来源<input value={metadataForm.venue} onChange={(event) => updateMetadataField('venue', event.target.value)} /></label>
                </div>
                <label>摘要<textarea value={metadataForm.abstract} onChange={(event) => updateMetadataField('abstract', event.target.value)} /></label>
                <div className="metadata-editor-grid">
                  <label>DOI<input value={metadataForm.doi} onChange={(event) => updateMetadataField('doi', event.target.value)} /></label>
                  <label>arXiv<input value={metadataForm.arxiv_id} onChange={(event) => updateMetadataField('arxiv_id', event.target.value)} /></label>
                </div>
                <label>来源 URL<input value={metadataForm.source_url} onChange={(event) => updateMetadataField('source_url', event.target.value)} /></label>
                <label>关键词<input value={metadataForm.keywords} onChange={(event) => updateMetadataField('keywords', event.target.value)} /></label>
                <div className="inline-actions">
                  <button type="button" onClick={saveMetadata} disabled={metadataSaving}>{metadataSaving ? '保存中...' : '保存元数据'}</button>
                  <button type="button" className="secondary-button" onClick={requestMetadataSuggestion} disabled={suggestionLoading}>
                    {suggestionLoading ? '补全中...' : 'AI + web-search 补全'}
                  </button>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => {
                      if (paper) setMetadataForm(metadataFormFromPaper(paper));
                      setMetadataEditing(false);
                    }}
                  >
                    取消
                  </button>
                </div>
                {metadataSuggestion && (
                  <div className="metadata-suggestion">
                    <strong>补全建议 · 置信度 {Math.round(Number(metadataSuggestion.suggestions.confidence ?? 0) * 100)}%</strong>
                    <p>{metadataSuggestion.suggestions.notes || '请核对建议后再应用到表单。'}</p>
                    {(metadataSuggestion.candidates ?? []).length > 0 && (
                      <div className="metadata-candidate-list">
                        {(metadataSuggestion.candidates ?? []).map((candidate, index) => (
                          <button
                            type="button"
                            className={selectedMetadataCandidate === index ? 'metadata-candidate active' : 'metadata-candidate'}
                            key={`${candidate.source_url || candidate.title}-${index}`}
                            onClick={() => setSelectedMetadataCandidate(index)}
                          >
                            <strong>{candidate.title || '未命名候选'}</strong>
                            <span>{[candidate.year, candidate.venue, candidate.source].filter(Boolean).join(' / ') || '候选来源待核对'}</span>
                          </button>
                        ))}
                      </div>
                    )}
                    {metadataSuggestion.evidence.length > 0 && (
                      <div className="metadata-evidence-list">
                        {metadataSuggestion.evidence.slice(0, 3).map((item) => (
                          <a key={`${item.url}-${item.title}`} href={item.url} target="_blank" rel="noreferrer">
                            <strong>{item.title || item.url}</strong>
                            {item.snippet && <span>{item.snippet}</span>}
                          </a>
                        ))}
                      </div>
                    )}
                    <button type="button" className="secondary-button" onClick={applyMetadataSuggestion}>应用到表单</button>
                  </div>
                )}
                <div className="metadata-suggestion metadata-reference-import">
                  <strong>参考文献批量补全</strong>
                  <p>可粘贴 Zotero / EndNote 导出的 RIS、BibTeX，或普通参考文献文本，解析后选择候选应用到表单。</p>
                  <textarea
                    value={referenceContent}
                    onChange={(event) => setReferenceContent(event.target.value)}
                    placeholder="RIS: TY  - JOUR / TI  - ... / AU  - ... / ER  -；或 BibTeX: @article{...}"
                  />
                  <div className="inline-actions">
                    <button type="button" className="secondary-button" onClick={parseReferenceMetadata} disabled={referenceLoading}>
                      {referenceLoading ? '解析中...' : '解析参考文献'}
                    </button>
                    <button type="button" className="secondary-button" onClick={applyReferenceCandidate} disabled={selectedReferenceCandidate < 0 || referenceCandidates.length === 0}>
                      应用选中候选
                    </button>
                  </div>
                  {referenceCandidates.length > 0 && (
                    <div className="metadata-candidate-list">
                      {referenceCandidates.map((candidate, index) => (
                        <button
                          type="button"
                          className={selectedReferenceCandidate === index ? 'metadata-candidate active' : 'metadata-candidate'}
                          key={`${candidate.source}-${candidate.title}-${index}`}
                          onClick={() => setSelectedReferenceCandidate(index)}
                        >
                          <strong>{candidate.title || '未命名候选'}</strong>
                          <span>{[candidate.year, candidate.venue, candidate.source].filter(Boolean).join(' / ') || '参考文献候选'}</span>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              </div>
            )}
          </article>

          <PaperReadingPanel paper={paper} />

          <article className="detail-card">
            <h2>主题词</h2>
            <div className="tag-cloud">
              {(paper.light_profile?.keywords.length ? paper.light_profile.keywords : paper.keywords).map((keyword) => (
                <span key={keyword}>{keyword}</span>
              ))}
              {paper.keywords.length === 0 && !paper.light_profile?.keywords.length && <span>主题词待提取</span>}
            </div>
          </article>

        </aside>
      </section>
      )}

      {activeTab === 'pdf' && (
        <section className="detail-card">
          <div className="panel-title">
            <div>
              <p className="eyebrow">PDF</p>
              <h2>原始论文</h2>
            </div>
            {paper.has_pdf && (
              <a className="secondary-button link-button" href={`/api/papers/${paper.id}/pdf/?download=1`}>
                导出 PDF
              </a>
            )}
          </div>
          {paper.has_pdf ? (
            <section className="pdf-frame-shell embedded">
              <iframe title={`${paper.title} PDF`} src={`/api/papers/${paper.id}/pdf/`} />
            </section>
          ) : (
            <EmptyState title="暂无 PDF 文件" note="这条论文记录还没有绑定可查看的 PDF。" />
          )}
        </section>
      )}

      {activeTab === 'qa' && (
        <section className="detail-card">
          <div className="panel-title">
            <div>
              <p className="eyebrow">问答</p>
              <h2>只问这篇论文</h2>
            </div>
          </div>
          <div className="paper-qa-box">
            <div className="segmented-control">
              <button type="button" className={qaMode === 'compressed' ? 'active' : ''} onClick={() => setQaMode('compressed')}>
                压缩概览
              </button>
              <button type="button" className={qaMode === 'preview' ? 'active' : ''} onClick={() => setQaMode('preview')}>
                概览 + 原文预览
              </button>
            </div>
            <textarea
              value={qaQuestion}
              onChange={(event) => setQaQuestion(event.target.value)}
              placeholder="例如：这篇论文的方法创新点是什么？"
            />
            <button type="button" onClick={askCurrentPaper} disabled={qaLoading}>
              {qaLoading ? '回答中...' : '提问'}
            </button>
            {qaError && <div className="form-message form-message-error">{qaError}</div>}
            {qaHistoryError && <div className="form-message form-message-error">{qaHistoryError}</div>}
            <div className="qa-history-list">
              {qaHistory.map((item) => (
                <article className="paper-qa-answer" key={item.id}>
                  <span>{formatFullDate(item.created_at)} · {item.model}</span>
                  <strong>{item.question}</strong>
                  <p>{item.answer}</p>
                  <small>使用内容：{item.sources[0]?.used_sections?.join('、') || '已保存上下文'}</small>
                </article>
              ))}
              {qaHistory.length === 0 && <EmptyState title="暂无问答记录" note="提交问题后，回答会保存在这里。" />}
            </div>
          </div>
        </section>
      )}
    </main>
  );
}

function PaperPdfPage() {
  const { id } = useParams();
  const { data: paper, loading, error } = useApiData<Paper | null>(
    id ? `/api/papers/${id}/` : '/api/papers/0/',
    null
  );

  if (loading) {
    return (
      <main className="page">
        <EmptyState title="正在读取 PDF" note="正在加载论文信息和 PDF 预览。" />
      </main>
    );
  }

  if (error || !paper) {
    return (
      <main className="page">
        <EmptyState title="论文不存在或暂时不可用" note="可以回到论文目录重新选择。" />
      </main>
    );
  }

  return (
    <main className="page pdf-page">
      <header className="paper-hero">
        <div>
          <p className="eyebrow">PDF 内容</p>
          <h1>{paper.title}</h1>
          <p className="lede">直接查看系统保存的原始 PDF。后续深度解析会补充结构化章节和图表内容。</p>
        </div>
        <div className="detail-actions">
          <Link className="secondary-button link-button" to={`/papers/${paper.id}`}>
            返回详情
          </Link>
          {paper.has_pdf && (
            <a className="secondary-button link-button" href={`/api/papers/${paper.id}/pdf/?download=1`}>
              导出 PDF
            </a>
          )}
        </div>
      </header>
      {paper.has_pdf ? (
        <section className="pdf-frame-shell">
          <iframe title={`${paper.title} PDF`} src={`/api/papers/${paper.id}/pdf/`} />
        </section>
      ) : (
        <EmptyState title="暂无 PDF 文件" note="这条论文记录还没有绑定可查看的 PDF。" />
      )}
    </main>
  );
}

function PaperQA() {
  const { data: papers, loading, error } = useApiData<Paper[]>('/api/papers/', []);
  const [query, setQuery] = useState('');
  const [year, setYear] = useState<string>('all');
  const [keywordInput, setKeywordInput] = useState('');
  const [paperCodeInput, setPaperCodeInput] = useState('');
  const [selectedIds, setSelectedIds] = useState<Set<number>>(() => new Set());
  const [question, setQuestion] = useState('');
  const [mode, setMode] = useState<'compressed' | 'preview'>('compressed');
  const [answer, setAnswer] = useState<PaperQaResponse | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [qaError, setQaError] = useState('');

  const years = useMemo(() => {
    return Array.from(new Set(papers.map((paper) => paper.year).filter((item): item is number => Boolean(item)))).sort(
      (a, b) => b - a
    );
  }, [papers]);
  const requiredKeywords = useMemo(() => splitKeywords(keywordInput), [keywordInput]);
  const visiblePapers = useMemo(() => {
    const normalizedQuery = query.trim().toLowerCase();
    return papers.filter((paper) => {
      const keywordText = paper.keywords.join(' ').toLowerCase();
      const fuzzyMatch =
        !normalizedQuery ||
        paper.title.toLowerCase().includes(normalizedQuery) ||
        paperCode(paper).toLowerCase().includes(normalizedQuery) ||
        paper.abstract.toLowerCase().includes(normalizedQuery) ||
        keywordText.includes(normalizedQuery) ||
        (paper.venue ?? '').toLowerCase().includes(normalizedQuery);
      const yearMatch = year === 'all' || String(paper.year ?? '') === year;
      const requiredMatch = requiredKeywords.every((keyword) =>
        paper.keywords.some((paperKeyword) => paperKeyword.toLowerCase() === keyword.toLowerCase())
      );
      return fuzzyMatch && yearMatch && requiredMatch;
    });
  }, [papers, query, requiredKeywords, year]);
  const selectedPapers = useMemo(() => papers.filter((paper) => selectedIds.has(paper.id)), [papers, selectedIds]);
  const allVisibleSelected = visiblePapers.length > 0 && visiblePapers.every((paper) => selectedIds.has(paper.id));

  function togglePaper(id: number) {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  }

  function toggleVisiblePapers() {
    setSelectedIds((current) => {
      const next = new Set(current);
      if (allVisibleSelected) {
        visiblePapers.forEach((paper) => next.delete(paper.id));
      } else {
        visiblePapers.forEach((paper) => next.add(paper.id));
      }
      return next;
    });
  }

  function removeSelectedPaper(paperId: number) {
    setSelectedIds((current) => {
      const next = new Set(current);
      next.delete(paperId);
      return next;
    });
  }

  function clearSelectedPapers() {
    setSelectedIds(new Set());
  }

  function addPapersByCode() {
    const ids = parsePaperCodeInput(paperCodeInput);
    if (ids.length === 0) {
      setQaError('请输入论文编号，例如 P000003。');
      return;
    }
    const paperByCode = new Map(papers.map((paper) => [paperCode(paper).toUpperCase(), paper]));
    const found = ids.map((id) => paperByCode.get(paperCode(id))).filter((paper): paper is Paper => Boolean(paper));
    const missing = ids.filter((id) => !paperByCode.has(paperCode(id)));
    setSelectedIds((current) => {
      const next = new Set(current);
      found.forEach((paper) => next.add(paper.id));
      return next;
    });
    setPaperCodeInput('');
    setQaError(missing.length > 0 ? `找不到论文编号：${missing.map((id) => paperCode(id)).join('、')}` : '');
  }

  async function submitQuestion() {
    setQaError('');
    setAnswer(null);
    if (selectedIds.size === 0) {
      setQaError('请先选择至少一篇论文。');
      return;
    }
    if (!question.trim()) {
      setQaError('请先输入问题。');
      return;
    }
    setSubmitting(true);
    try {
      const response = await apiFetch('/api/qa/papers/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          paper_ids: Array.from(selectedIds),
          question: question.trim(),
          mode
        })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) {
        throw new Error(payloadMessage(payload, '问答服务暂时不可用。'));
      }
      setAnswer(payload as PaperQaResponse);
    } catch (err) {
      setQaError(err instanceof Error ? err.message : '问答服务暂时不可用。');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <main className="page">
      <Header
        eyebrow="Cross-paper QA"
        title="跨论文分析"
        description="选定论文集合后进行比较、归纳与追问；回答限定在所选范围内，并保留来源线索。"
      />
      <section className="qa-layout">
        <div className="selection-pane">
          <div className="section-heading">
            <div>
              <span>来源范围</span>
              <h2>选择参与分析的论文</h2>
            </div>
            <strong>{selectedIds.size} 篇</strong>
          </div>
          <div className="qa-filter-panel">
            <input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="按题名、摘要、关键词模糊搜索" />
            <div className="paper-code-add">
              <input
                value={paperCodeInput}
                onChange={(event) => setPaperCodeInput(event.target.value)}
                placeholder="按编号添加，例如 P000003"
              />
              <button type="button" className="secondary-button" onClick={addPapersByCode}>
                添加
              </button>
            </div>
            <input value={keywordInput} onChange={(event) => setKeywordInput(event.target.value)} placeholder="必须包含关键词，用逗号分隔" />
            <div className="year-strip">
              <button type="button" className={year === 'all' ? 'active' : ''} onClick={() => setYear('all')}>
                全部年份
              </button>
              {years.map((item) => (
                <button type="button" className={year === String(item) ? 'active' : ''} onClick={() => setYear(String(item))} key={item}>
                  {item}
                </button>
              ))}
            </div>
            <label className="select-all-line">
              <input type="checkbox" checked={allVisibleSelected} onChange={toggleVisiblePapers} />
              <span>全选当前结果</span>
            </label>
          </div>
          <SelectedPaperPanel
            papers={selectedPapers}
            onRemove={removeSelectedPaper}
            onClear={clearSelectedPapers}
            emptyText="可以从列表勾选，也可以按编号快速加入问答范围。"
          />
          {loading ? (
            <EmptyState title="正在读取论文列表" note="稍后即可选择问答范围。" />
          ) : error ? (
            <EmptyState title="论文列表暂时不可用" note="请先检查后端服务状态。" />
          ) : visiblePapers.length === 0 ? (
            <EmptyState title="没有匹配的论文" note="可以放宽年份或关键词条件。" />
          ) : (
            <div className="qa-paper-list">
              {visiblePapers.map((paper) => (
                <label className="qa-paper-item" key={paper.id}>
                  <input type="checkbox" checked={selectedIds.has(paper.id)} onChange={() => togglePaper(paper.id)} />
                  <span>
                    <strong>
                      <span className="paper-code paper-code-inline">{paperCode(paper)}</span>
                      {paper.title}
                    </strong>
                    <small>
                      {paper.year ?? '年份未知'} / {paper.venue || '来源未标注'} / {paper.light_profile ? '已有轻处理概览' : '待处理'}
                    </small>
                  </span>
                </label>
              ))}
            </div>
          )}
        </div>
        <div className="answer-pane">
          <div className="section-heading">
            <div>
              <span>MiniMax-M2.7</span>
              <h2>提出问题</h2>
            </div>
          </div>
          <div className="segmented-control">
            <button type="button" className={mode === 'compressed' ? 'active' : ''} onClick={() => setMode('compressed')}>
              压缩概览
            </button>
            <button type="button" className={mode === 'preview' ? 'active' : ''} onClick={() => setMode('preview')}>
              概览 + 原文预览
            </button>
          </div>
          <textarea
            value={question}
            onChange={(event) => setQuestion(event.target.value)}
            placeholder="例如：这些论文在处理长时间 PDE 动力学时，方法上有什么共同点和差异？"
          />
          <button type="button" onClick={submitQuestion} disabled={submitting || selectedIds.size === 0}>
            {submitting ? '分析中...' : '开始分析'}
          </button>
          <SelectedPaperPanel
            papers={selectedPapers}
            onRemove={removeSelectedPaper}
            onClear={clearSelectedPapers}
            emptyText="已勾选论文会显示在这里，回答只基于这些论文。"
          />
          {qaError && <div className="form-message form-message-error">{qaError}</div>}
          {answer && (
            <article className="qa-answer">
              <div className="section-heading">
                <div>
                  <span>{answer.model}</span>
                  <h2>回答</h2>
                </div>
                {typeof answer.usage?.total_tokens === 'number' && <strong>{answer.usage.total_tokens} tokens</strong>}
              </div>
              {answer.context_warning && (
                <div className="form-message">
                  {answer.context_warning}
                  {typeof answer.estimated_context_tokens === 'number' && typeof answer.context_token_limit === 'number'
                    ? ` 当前估算 ${answer.estimated_context_tokens} / ${answer.context_token_limit} tokens。`
                    : ''}
                </div>
              )}
              <p>{answer.answer}</p>
              <div className="source-list">
                <strong>来源范围</strong>
                {answer.sources.map((source) => (
                  <div key={source.id}>
                    <span>#{source.id} {source.title}</span>
                    <small>{source.used_sections.join('、')}</small>
                  </div>
                ))}
              </div>
            </article>
          )}
        </div>
      </section>
    </main>
  );
}

function KnowledgeSpaceManager() {
  const [reloadToken, setReloadToken] = useState(0);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [name, setName] = useState('');
  const [description, setDescription] = useState('');
  const [parentId, setParentId] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const { data: spaces, loading, error: loadError } = useApiData<KnowledgeSpace[]>(
    `/api/knowledge-spaces/?kind=docs&reload=${reloadToken}`,
    []
  );
  const orderedSpaces = useMemo(
    () => [...spaces].sort((a, b) => (a.path ?? a.name).localeCompare(b.path ?? b.name, 'zh-CN')),
    [spaces]
  );
  const selected = orderedSpaces.find((space) => space.id === selectedId) ?? null;

  useEffect(() => {
    if (selectedId === null && orderedSpaces.length > 0) {
      setSelectedId(orderedSpaces[0].id);
    }
    if (selectedId !== null && orderedSpaces.length > 0 && !orderedSpaces.some((space) => space.id === selectedId)) {
      setSelectedId(orderedSpaces[0].id);
    }
  }, [orderedSpaces, selectedId]);

  async function createSpace() {
    setMessage('');
    setError('');
    if (!name.trim()) {
      setError('请先填写知识体系名称。');
      return;
    }
    try {
      const response = await apiFetch('/api/knowledge-spaces/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: name.trim(),
          description: description.trim(),
          kind: 'docs',
          parent_id: parentId ? Number(parentId) : null
        })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '创建失败，请检查名称和父级设置。'));
      const created = payload as KnowledgeSpace;
      setName('');
      setDescription('');
      setParentId('');
      setSelectedId(created.id);
      setMessage('知识体系已创建。');
      setReloadToken((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建失败，请稍后重试。');
    }
  }

  async function archiveSelected() {
    if (!selected) return;
    const confirmed = window.confirm(`确认停用“${selected.path ?? selected.name}”？已有文档不会被删除，只是不再把这个体系作为可用分类。`);
    if (!confirmed) return;
    setMessage('');
    setError('');
    try {
      const response = await apiFetch(`/api/knowledge-spaces/${selected.id}/archive/`, { method: 'POST' });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '停用失败，请稍后重试。'));
      setSelectedId(null);
      setMessage('知识体系已停用，已有文档仍会保留。');
      setReloadToken((value) => value + 1);
    } catch (err) {
      setError(err instanceof Error ? err.message : '停用失败，请稍后重试。');
    }
  }

  return (
    <main className="page taxonomy-page">
      <Header
        eyebrow="Knowledge Taxonomy"
        title="知识体系管理"
        description="维护团队文档的稳定分类框架，区分知识类别与临时标签；停用分类不会删除已有文档。"
      />
      <section className="taxonomy-layout">
        <aside className="taxonomy-tree" aria-label="知识体系列表">
          <div className="section-heading">
            <div>
              <span>目录树</span>
              <h2>文档分类</h2>
            </div>
            <strong>{orderedSpaces.length}</strong>
          </div>
          {loading ? (
            <p className="taxonomy-muted">正在读取知识体系...</p>
          ) : loadError ? (
            <p className="taxonomy-muted">知识体系暂时不可用，请稍后刷新。</p>
          ) : orderedSpaces.length === 0 ? (
            <p className="taxonomy-muted">还没有知识体系，可以先创建一个一级分类。</p>
          ) : (
            <div className="taxonomy-tree-list">
              {orderedSpaces.map((space) => (
                <button
                  key={space.id}
                  type="button"
                  className={selectedId === space.id ? 'active' : ''}
                  style={{ paddingLeft: 12 + (space.depth ?? 0) * 18 }}
                  onClick={() => setSelectedId(space.id)}
                >
                  <span>{space.name}</span>
                  <small>{space.descendant_count ?? 0} 个子级</small>
                </button>
              ))}
            </div>
          )}
        </aside>
        <section className="taxonomy-detail">
          {selected ? (
            <>
              <p className="eyebrow">当前选择</p>
              <h2>{selected.path ?? selected.name}</h2>
              <dl className="taxonomy-meta">
                <div>
                  <dt>路径</dt>
                  <dd>{selected.path ?? selected.name}</dd>
                </div>
                <div>
                  <dt>层级</dt>
                  <dd>第 {(selected.depth ?? 0) + 1} 级</dd>
                </div>
                <div>
                  <dt>子级数量</dt>
                  <dd>{selected.descendant_count ?? 0}</dd>
                </div>
              </dl>
              <p>{selected.description || '这个知识体系还没有说明。'}</p>
              <button type="button" className="danger-button" onClick={archiveSelected}>
                停用体系
              </button>
            </>
          ) : (
            <p className="taxonomy-muted">请选择左侧知识体系查看详情，或在右侧创建新的分类。</p>
          )}
        </section>
        <section className="taxonomy-form">
          <h2>新建知识体系</h2>
          <label>
            <span>名称</span>
            <input value={name} onChange={(event) => setName(event.target.value)} placeholder="例如：深度学习" />
          </label>
          <label>
            <span>说明</span>
            <textarea
              value={description}
              onChange={(event) => setDescription(event.target.value)}
              placeholder="说明这个体系收纳哪些内容"
            />
          </label>
          <label>
            <span>父级</span>
            <select value={parentId} onChange={(event) => setParentId(event.target.value)}>
              <option value="">作为一级体系</option>
              {orderedSpaces.map((space) => (
                <option key={space.id} value={space.id}>
                  {space.path ?? space.name}
                </option>
              ))}
            </select>
          </label>
          <button type="button" onClick={createSpace}>
            创建
          </button>
          {(message || error) && (
            <div className={error ? 'form-message form-message-error' : 'form-message'}>{error || message}</div>
          )}
        </section>
      </section>
    </main>
  );
}

function DocsLibrary() {
  const [docsReloadToken, setDocsReloadToken] = useState(0);
  const [draftQuery, setDraftQuery] = useState('');
  const [draftStatus, setDraftStatus] = useState('all');
  const [selectedSpaceId, setSelectedSpaceId] = useState<string>('');
  const [appliedFilters, setAppliedFilters] = useState({ query: '', status: 'all', page: 1, pageSize: 25 });
  const documentsUrl = useMemo(
    () =>
      buildPagedDocumentListUrl({
        spaceId: selectedSpaceId,
        query: appliedFilters.query,
        status: appliedFilters.status,
        page: appliedFilters.page,
        pageSize: appliedFilters.pageSize,
        reloadToken: docsReloadToken
      }),
    [appliedFilters, docsReloadToken, selectedSpaceId]
  );
  const { data: documentData, loading, error } = useApiData<DocumentListResponse>(documentsUrl, emptyDocumentList);
  const { data: spaces } = useApiData<KnowledgeSpace[]>('/api/knowledge-spaces/?kind=docs', []);
  const docs = documentData.results;
  const childSpaces = useMemo(() => {
    const grouped = new Map<number | null, KnowledgeSpace[]>();
    spaces.forEach((space) => {
      grouped.set(space.parent_id, [...(grouped.get(space.parent_id) ?? []), space]);
    });
    return grouped;
  }, [spaces]);
  const spacesById = useMemo(() => new Map(spaces.map((space) => [space.id, space])), [spaces]);
  const docsBySpace = useMemo(() => {
    const grouped = new Map<number | 'ungrouped', Doc[]>();
    docs.forEach((doc) => {
      const key = doc.space_id ?? 'ungrouped';
      grouped.set(key, [...(grouped.get(key) ?? []), doc]);
    });
    return grouped;
  }, [docs]);
  const groupedSections = useMemo(() => {
    const sections = spaces
      .filter((space) => (docsBySpace.get(space.id)?.length ?? 0) > 0)
      .map((space) => ({ key: `space-${space.id}`, name: space.path ?? space.name, docs: docsBySpace.get(space.id) ?? [] }));
    docsBySpace.forEach((items, key) => {
      if (key === 'ungrouped') sections.push({ key, name: '未分组', docs: items });
      else if (!spacesById.has(key)) sections.push({ key: `unknown-${key}`, name: `未知空间 #${key}`, docs: items });
    });
    return sections;
  }, [docsBySpace, spaces, spacesById]);

  const applyDocsSearch = () => {
    setAppliedFilters((current) => ({ ...current, query: draftQuery.trim(), status: draftStatus, page: 1 }));
  };

  const resetDocsSearch = () => {
    setDraftQuery('');
    setDraftStatus('all');
    setSelectedSpaceId('');
    setAppliedFilters((current) => ({ ...current, query: '', status: 'all', page: 1 }));
    setDocsReloadToken((value) => value + 1);
  };

  const chooseSpace = (spaceId: string) => {
    setSelectedSpaceId(spaceId);
    setAppliedFilters((current) => ({ ...current, page: 1 }));
  };

  const changePage = (page: number) => {
    setAppliedFilters((current) => ({ ...current, page: Math.max(1, Math.min(documentData.total_pages, page)) }));
  };

  const changePageSize = (pageSize: number) => {
    setAppliedFilters((current) => ({ ...current, page: 1, pageSize }));
  };

  const renderSpaceNode = (space: KnowledgeSpace, depth = 0) => {
    const children = childSpaces.get(space.id) ?? [];
    return (
      <div className="doc-space-node" key={space.id}>
        <button
          type="button"
          className={selectedSpaceId === String(space.id) ? 'active' : ''}
          onClick={() => chooseSpace(String(space.id))}
          style={{ paddingLeft: 10 + depth * 14 }}
        >
          <span>{space.name}</span>
          <small>选择</small>
        </button>
        {children.map((child) => renderSpaceNode(child, depth + 1))}
      </div>
    );
  };

  return (
    <main className="page docs-page">
      <Header
        eyebrow="Knowledge Documents"
        title="知识文档库"
        description="沉淀方法笔记、工具手册与领域知识，按知识体系独立组织；正文默认采用中文 Markdown。"
      />
      <section className="docs-command-bar">
        <div className="inline-actions">
          <Link className="secondary-button link-button" to="/docs/new">
            新建 Markdown 文档
          </Link>
          <Link className="secondary-button link-button" to="/knowledge-spaces">
            知识体系管理
          </Link>
        </div>
        <span>共 {documentData.count} 篇文档</span>
      </section>
      <section className="docs-filter-panel">
        <label>
          <span>知识分类</span>
          <select value={selectedSpaceId} onChange={(event) => chooseSpace(event.target.value)}>
            <option value="">全部文档</option>
            <option value="ungrouped">未分组</option>
            {spaces.map((space) => (
              <option key={space.id} value={space.id}>
                {space.path ?? space.name}
              </option>
            ))}
          </select>
        </label>
        <label>
          <span>搜索文档</span>
          <input
            value={draftQuery}
            onChange={(event) => setDraftQuery(event.target.value)}
            placeholder="按编号、标题、摘要或关键词搜索，例如 D000123"
          />
        </label>
        <label>
          <span>状态</span>
          <select value={draftStatus} onChange={(event) => setDraftStatus(event.target.value)}>
            <option value="all">全部状态</option>
            <option value="draft">草稿</option>
            <option value="published">已发布</option>
            <option value="archived">已归档</option>
          </select>
        </label>
        <div className="search-command-group">
          <button type="button" onClick={applyDocsSearch}>
            开始筛选
          </button>
          <button type="button" className="secondary-button" onClick={resetDocsSearch}>
            重置
          </button>
        </div>
      </section>
      {loading ? (
        <EmptyState title="正在读取文档目录" note="文档库会按知识空间组织。" />
      ) : error ? (
        <EmptyState title="文档目录暂时不可用" note="后端目录接口没有返回数据，请先检查服务状态。" />
      ) : docs.length === 0 ? (
        <EmptyState title="暂无匹配文档" note="可以放宽搜索词、状态或知识分类。" />
      ) : (
        <section className="docs-layout">
          <aside className="doc-space-tree">
            <div className="section-heading">
              <div>
                <span>知识体系</span>
                <h2>文档分级</h2>
              </div>
            </div>
            <div className="doc-space-node">
              <button type="button" className={selectedSpaceId === '' ? 'active' : ''} onClick={() => chooseSpace('')}>
                <span>全部文档</span>
                <small>总览</small>
              </button>
              <button type="button" className={selectedSpaceId === 'ungrouped' ? 'active' : ''} onClick={() => chooseSpace('ungrouped')}>
                <span>未分组</span>
                <small>选择</small>
              </button>
            </div>
            {spaces.length > 0 ? (
              <div>{(childSpaces.get(null) ?? []).map((space) => renderSpaceNode(space))}</div>
            ) : (
              <p>还没有配置知识空间，文档会先放在“未分组”。</p>
            )}
          </aside>
          <div className="doc-group-list">
            <section className="result-toolbar">
              <div className="result-actions">
                <select value={appliedFilters.pageSize} onChange={(event) => changePageSize(Number(event.target.value))}>
                  <option value={25}>每页 25</option>
                  <option value={50}>每页 50</option>
                  <option value={100}>每页 100</option>
                </select>
                <div className="result-meta result-meta-inline">
                  <strong>共 {documentData.count} 篇</strong>
                  <span>第 {documentData.page} / {documentData.total_pages} 页</span>
                </div>
                <button type="button" className="secondary-button" disabled={documentData.page <= 1} onClick={() => changePage(documentData.page - 1)}>
                  上一页
                </button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={documentData.page >= documentData.total_pages}
                  onClick={() => changePage(documentData.page + 1)}
                >
                  下一页
                </button>
              </div>
            </section>
            {groupedSections.map((section) => (
              <section className="doc-group" key={section.key}>
                <div className="section-heading">
                  <div>
                    <span>{section.docs.length} 篇文档</span>
                    <h2>{section.name}</h2>
                  </div>
                </div>
                <div className="table-panel">
                  {section.docs.map((doc) => (
                    <article className="row-card" key={doc.id}>
                      <div>
                        <div className="paper-title-row">
                          <span className="paper-code">{docCode(doc)}</span>
                        </div>
                        <Link className="paper-title-link" to={`/docs/${doc.id}`}>
                          {doc.title}
                        </Link>
                        <p>
                          {doc.space_path ?? doc.space ?? '未分组'} / v{doc.current_version ?? 1} / 更新 {formatDate(doc.updated_at)}
                        </p>
                        {doc.summary && <p>{doc.summary}</p>}
                        {doc.keywords.length > 0 && (
                          <div className="mini-tags">
                            {doc.keywords.slice(0, 6).map((keyword) => (
                              <span key={keyword}>{keyword}</span>
                            ))}
                          </div>
                        )}
                      </div>
                      <div className="row-actions">
                        <StatusPill value={doc.status} />
                        <Link className="secondary-button link-button" to={`/docs/${doc.id}`}>
                          查看/编辑
                        </Link>
                      </div>
                    </article>
                  ))}
                </div>
              </section>
            ))}
          </div>
        </section>
      )}
    </main>
  );
}

function DocumentEditor({
  initialDoc,
  mode
}: {
  initialDoc?: Doc | null;
  mode: 'create' | 'edit';
}) {
  const navigate = useNavigate();
  const [spacesReloadToken, setSpacesReloadToken] = useState(0);
  const { data: spaces } = useApiData<KnowledgeSpace[]>(`/api/knowledge-spaces/?kind=docs&reload=${spacesReloadToken}`, []);
  const [createdSpaces, setCreatedSpaces] = useState<KnowledgeSpace[]>([]);
  const [title, setTitle] = useState(initialDoc?.title ?? '');
  const [summary, setSummary] = useState(initialDoc?.summary ?? '');
  const [status, setStatus] = useState(initialDoc?.status ?? 'draft');
  const [spaceId, setSpaceId] = useState('');
  const [newSpaceName, setNewSpaceName] = useState('');
  const [newSpaceParentId, setNewSpaceParentId] = useState('');
  const [keywordText, setKeywordText] = useState((initialDoc?.keywords ?? []).join(', '));
  const [markdown, setMarkdown] = useState(initialDoc?.markdown ?? '');
  const [viewMode, setViewMode] = useState<'edit' | 'preview'>('edit');
  const [uploadedImages, setUploadedImages] = useState<UploadedImage[]>([]);
  const [saving, setSaving] = useState(false);
  const [creatingSpace, setCreatingSpace] = useState(false);
  const [uploadingImage, setUploadingImage] = useState(false);
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');
  const availableSpaces = useMemo(() => {
    const byId = new Map<number, KnowledgeSpace>();
    spaces.forEach((space) => byId.set(space.id, space));
    createdSpaces.forEach((space) => byId.set(space.id, space));
    return Array.from(byId.values()).sort((a, b) => a.order - b.order || a.name.localeCompare(b.name, 'zh-CN'));
  }, [createdSpaces, spaces]);

  useEffect(() => {
    if (!initialDoc) return;
    setTitle(initialDoc.title);
    setSummary(initialDoc.summary);
    setStatus(initialDoc.status);
    setSpaceId(initialDoc.space_id ? String(initialDoc.space_id) : '');
    setKeywordText(initialDoc.keywords.join(', '));
    setMarkdown(initialDoc.markdown ?? '');
  }, [initialDoc]);

  useEffect(() => {
    if (!initialDoc || initialDoc.space_id || !initialDoc.space || availableSpaces.length === 0) return;
    const matched = availableSpaces.find((space) => space.slug === initialDoc.space_slug || space.path === initialDoc.space_path);
    setSpaceId(matched ? String(matched.id) : '');
  }, [availableSpaces, initialDoc]);

  async function saveDocument() {
    setError('');
    setMessage('');
    if (!title.trim()) {
      setError('请先填写文档标题。');
      return;
    }
    setSaving(true);
    try {
      const response = await apiFetch(mode === 'create' ? '/api/documents/' : `/api/documents/${initialDoc?.id}/`, {
        method: mode === 'create' ? 'POST' : 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: title.trim(),
          summary: summary.trim(),
          status,
          space_id: spaceId ? Number(spaceId) : null,
          keywords: splitKeywords(keywordText),
          markdown
        })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '文档保存失败。'));
      setMessage('文档已保存。');
      if (mode === 'create' && 'id' in payload) {
        navigate(`/docs/${payload.id}`);
      } else {
        window.setTimeout(() => window.location.reload(), 250);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '文档保存失败。');
    } finally {
      setSaving(false);
    }
  }

  async function uploadImageFile(image: File, insertAt?: { start: number; end: number }) {
    setError('');
    setMessage('');
    setUploadingImage(true);
    try {
      const formData = new FormData();
      formData.append('image', image);
      const response = await apiFetch('/api/storage/upload-image/', {
        method: 'POST',
        body: formData
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '图片上传失败。'));
      const markdownImage = 'markdown' in payload && typeof payload.markdown === 'string' ? payload.markdown : '';
      if (!markdownImage) throw new Error('图片上传成功，但没有返回 Markdown 链接。');
      const url = 'url' in payload && typeof payload.url === 'string' ? payload.url : '';
      setUploadedImages((current) => [...current, { name: image.name, url, markdown: markdownImage }]);
      if (insertAt) {
        setMarkdown((current) => `${current.slice(0, insertAt.start)}${markdownImage}${current.slice(insertAt.end)}`);
        setMessage('图片已上传，并插入到 Markdown 正文。');
      } else {
        setMessage('图片已上传。可在右侧复制或插入引用地址。');
      }
      return markdownImage;
    } catch (err) {
      setError(err instanceof Error ? err.message : '图片上传失败。');
      return '';
    } finally {
      setUploadingImage(false);
    }
  }

  async function createKnowledgeSpace() {
    setError('');
    setMessage('');
    if (!newSpaceName.trim()) {
      setError('请先填写知识体系名称。');
      return;
    }
    setCreatingSpace(true);
    try {
      const response = await apiFetch('/api/knowledge-spaces/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          name: newSpaceName.trim(),
          kind: 'docs',
          parent_id: newSpaceParentId ? Number(newSpaceParentId) : null
        })
      });
      const payload = await readResponsePayload(response);
      if (!response.ok) throw new Error(payloadMessage(payload, '知识体系创建失败。'));
      const created = payload as KnowledgeSpace;
      setCreatedSpaces((current) => [...current, created]);
      setSpaceId(String(created.id));
      setNewSpaceName('');
      setNewSpaceParentId('');
      setSpacesReloadToken((value) => value + 1);
      setMessage(`已创建知识体系“${created.name}”，并设为当前文档分类。`);
    } catch (err) {
      setError(err instanceof Error ? err.message : '知识体系创建失败。');
    } finally {
      setCreatingSpace(false);
    }
  }

  async function handleMarkdownPaste(event: ClipboardEvent<HTMLTextAreaElement>) {
    const image = Array.from(event.clipboardData.files).find((file) => file.type.startsWith('image/'));
    if (!image) return;
    event.preventDefault();
    const target = event.currentTarget;
    await uploadImageFile(image, { start: target.selectionStart, end: target.selectionEnd });
  }

  async function handleImageInput(files: FileList | null) {
    const images = Array.from(files ?? []).filter((file) => file.type.startsWith('image/'));
    for (const image of images) {
      await uploadImageFile(image);
    }
  }

  function insertMarkdownReference(reference: string) {
    setMarkdown((current) => `${current}${current.endsWith('\n') || current.length === 0 ? '' : '\n'}${reference}\n`);
  }

  return (
    <section className="doc-editor-layout">
      <div className="doc-editor-main">
        <label>
          <span>标题</span>
          <input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="例如 Linux 文件系统入门" />
        </label>
        <label>
          <span>摘要</span>
          <input value={summary} onChange={(event) => setSummary(event.target.value)} placeholder="一句话说明这篇文档解决什么问题" />
        </label>
        <label>
          <span>Markdown 正文</span>
          <div className="editor-mode-tabs">
            <button type="button" className={viewMode === 'edit' ? 'active' : ''} onClick={() => setViewMode('edit')}>
              编辑源码
            </button>
            <button type="button" className={viewMode === 'preview' ? 'active' : ''} onClick={() => setViewMode('preview')}>
              预览效果
            </button>
          </div>
          {viewMode === 'edit' ? (
            <textarea
              className="markdown-editor"
              value={markdown}
              onChange={(event) => setMarkdown(event.target.value)}
              onPaste={handleMarkdownPaste}
              placeholder="# 标题&#10;&#10;用中文整理背景、步骤、命令、注意事项和参考资料。"
            />
          ) : (
            <div className="markdown-preview-panel">
              <MarkdownRenderer markdown={markdown} emptyText="正文为空，切回“编辑源码”开始撰写。" />
            </div>
          )}
        </label>
      </div>
      <aside className="doc-editor-side">
        <label>
          <span>所属知识体系</span>
          <select value={spaceId} onChange={(event) => setSpaceId(event.target.value)}>
            <option value="">未分组</option>
            {availableSpaces.map((space) => (
              <option key={space.id} value={space.id}>
                {space.name}
              </option>
            ))}
          </select>
        </label>
        <div className="space-create-box">
          <span>新建知识体系</span>
          <input value={newSpaceName} onChange={(event) => setNewSpaceName(event.target.value)} placeholder="例如 Linux 入门" />
          <select value={newSpaceParentId} onChange={(event) => setNewSpaceParentId(event.target.value)}>
            <option value="">作为一级分类</option>
            {availableSpaces.map((space) => (
              <option key={space.id} value={space.id}>
                作为“{space.name}”的子分类
              </option>
            ))}
          </select>
          <button type="button" className="secondary-button" disabled={creatingSpace} onClick={createKnowledgeSpace}>
            {creatingSpace ? '创建中...' : '创建并选中'}
          </button>
        </div>
        <label>
          <span>状态</span>
          <select value={status} onChange={(event) => setStatus(event.target.value)}>
            <option value="draft">草稿</option>
            <option value="published">已发布</option>
            <option value="archived">已归档</option>
          </select>
        </label>
        <label>
          <span>关键词</span>
          <input value={keywordText} onChange={(event) => setKeywordText(event.target.value)} placeholder="Linux, Shell" />
        </label>
        <div className="doc-image-uploader">
          <span>上传图片</span>
          <input type="file" accept="image/png,image/jpeg,image/webp,image/gif" multiple onChange={(event) => handleImageInput(event.target.files)} />
          <small>支持截图、实验曲线和报错图片。上传后会生成 Markdown 引用。</small>
          {uploadedImages.length > 0 && (
            <div className="uploaded-image-list">
              {uploadedImages.map((image) => (
                <div key={`${image.url}-${image.name}`}>
                  <strong>{image.name}</strong>
                  <code>{image.markdown}</code>
                  <button type="button" className="secondary-button" onClick={() => insertMarkdownReference(image.markdown)}>
                    插入引用
                  </button>
                </div>
              ))}
            </div>
          )}
        </div>
        <button type="button" onClick={saveDocument} disabled={saving}>
          {saving ? '保存中...' : '保存文档'}
        </button>
        {uploadingImage && <span className="muted-inline">图片上传中...</span>}
        <Link className="secondary-button link-button" to="/docs">
          返回文档库
        </Link>
        {(message || error) && (
          <div className={error ? 'form-message form-message-error' : 'form-message'}>{error || message}</div>
        )}
      </aside>
    </section>
  );
}

function NewDocument() {
  return (
    <main className="page doc-editor-page">
      <Header
        eyebrow="Knowledge Document"
        title="新建 Markdown 文档"
        description="创建可长期维护的团队知识条目，适合数值方法笔记、模型复现记录、工具链手册与专题综述。"
      />
      <DocumentEditor mode="create" />
    </main>
  );
}

function DocumentDetail() {
  const { id } = useParams();
  const [reloadToken, setReloadToken] = useState(0);
  const { data: doc, loading, error } = useApiData<Doc | null>(
    id ? `/api/documents/${id}/?reload=${reloadToken}` : '/api/documents/0/',
    null
  );
  const [editing, setEditing] = useState(false);
  const [viewMode, setViewMode] = useState<'rendered' | 'source'>('rendered');

  if (loading) {
    return (
      <main className="page">
        <EmptyState title="正在读取文档" note="正在加载 Markdown 正文和版本信息。" />
      </main>
    );
  }

  if (error || !doc) {
    return (
      <main className="page">
        <EmptyState title="文档不存在或暂时不可用" note="可以回到文档库重新选择。" />
      </main>
    );
  }

  return (
    <main className="page doc-detail-page">
      <header className="paper-hero">
        <div>
          <p className="eyebrow">知识文档</p>
          <h1>{doc.title}</h1>
          <p className="lede">{doc.summary || '暂无摘要。'}</p>
          <div className="detail-tags">
            <span>{docCode(doc)}</span>
            <StatusPill value={doc.status} />
            <span>v{doc.current_version ?? 1}</span>
            <span>{doc.space_path ?? doc.space ?? '未分组'}</span>
          </div>
        </div>
        <div className="detail-actions">
          <Link className="secondary-button link-button" to="/docs">
            返回文档库
          </Link>
          <button type="button" onClick={() => setEditing((value) => !value)}>
            {editing ? '查看正文' : '编辑文档'}
          </button>
        </div>
      </header>
      {editing ? (
        <DocumentEditor
          initialDoc={doc}
          mode="edit"
        />
      ) : (
        <section className="doc-viewer">
          <div className="doc-viewer-toolbar">
            <div className="segmented-control">
              <button type="button" className={viewMode === 'rendered' ? 'active' : ''} onClick={() => setViewMode('rendered')}>
                阅读视图
              </button>
              <button type="button" className={viewMode === 'source' ? 'active' : ''} onClick={() => setViewMode('source')}>
                查看源码
              </button>
            </div>
          </div>
          {viewMode === 'rendered' ? (
            <MarkdownRenderer markdown={doc.markdown} emptyText="这篇文档还没有正文。点击“编辑文档”开始补充。" />
          ) : (
            <pre>{doc.markdown || '这篇文档还没有正文。点击“编辑文档”开始补充。'}</pre>
          )}
        </section>
      )}
    </main>
  );
}

export function LegacyApp() {
  const { session, setSession, loading } = useAuthSession();
  const location = useLocation();
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window === 'undefined') return 'dark';
    const stored = window.localStorage.getItem('a510-theme');
    return stored === 'light' ? 'light' : 'dark';
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem('a510-theme', theme);
  }, [theme]);

  async function logout() {
    await apiFetch('/api/auth/logout/', { method: 'POST' });
    setSession({ authenticated: false, user: null });
  }

  if (loading) {
    return (
      <main className="login-page">
        <section className="login-panel">
          <div className="login-brand">
            <span>A510 知识库</span>
            <h1>正在恢复工作台会话</h1>
            <p>正在确认登录状态与后端服务可用性。</p>
          </div>
        </section>
      </main>
    );
  }

  if (!session.authenticated) {
    return <LoginScreen onLogin={setSession} />;
  }

  return (
    <div className="shell">
      <aside className="sidebar">
        <div className="brand">
          <span>A510 知识库</span>
          <small>AI for PDEs Research OS</small>
        </div>
        <nav className="sidebar-nav" aria-label="主导航">
          {navGroups.map((group) => (
            <section className="nav-group" key={group.label} aria-label={group.label}>
              <p>{group.label}</p>
              <div>
                {group.routes.map((route) => (
                  <NavLink
                    key={route.path}
                    to={route.path}
                    end={route.path === '/'}
                    className={({ isActive }) =>
                      isActive || isRouteSectionActive(route.path, location.pathname) ? 'active' : undefined
                    }
                  >
                    <span>{route.label}</span>
                    {route.description && <small>{route.description}</small>}
                  </NavLink>
                ))}
              </div>
            </section>
          ))}
        </nav>
        <div className="sidebar-session">
          <img src={defaultAvatar} alt="" />
          <div>
            <span>{session.user?.username}</span>
            <button type="button" onClick={logout}>退出登录</button>
          </div>
        </div>
      </aside>
      <div className="theme-toggle-floating" aria-label="色系切换">
        <button
          type="button"
          className={theme === 'light' ? 'active' : ''}
          onClick={() => setTheme('light')}
          title="切换浅色系"
        >
          ☼
        </button>
        <button
          type="button"
          className={theme === 'dark' ? 'active' : ''}
          onClick={() => setTheme('dark')}
          title="切换深色系"
        >
          ☾
        </button>
      </div>
      <Routes>
        <Route path="/" element={<DashboardHome />} />
        <Route path="/papers" element={<PaperLibrary />} />
        <Route path="/papers/upload" element={<UploadPaper />} />
        <Route path="/papers/qa" element={<PaperQA />} />
        <Route path="/papers/:id/pdf" element={<PaperPdfPage />} />
        <Route path="/papers/:id" element={<PaperDetail />} />
        <Route path="/docs" element={<DocsLibrary />} />
        <Route path="/docs/new" element={<NewDocument />} />
        <Route path="/docs/:id" element={<DocumentDetail />} />
        <Route path="/experiments" element={<ExperimentsView />} />
        <Route path="/materials" element={<MaterialsView />} />
        <Route path="/materials/:id" element={<MaterialDetailView />} />
        <Route path="/experiments/:id" element={<ExperimentDetailView />} />
        <Route path="/knowledge-spaces" element={<KnowledgeSpaceManager />} />
        <Route path="/knowledge-spaces/:id" element={<KnowledgeSpaceMapView />} />
        <Route path="/tasks" element={<TasksView />} />
        <Route path="/search" element={<SearchView />} />
        <Route path="/quality" element={<QualityIssuesView />} />
        <Route path="/assistant" element={<AssistantView />} />
        <Route path="/settings" element={<SettingsView />} />
        <Route path="*" element={<Placeholder title="页面不存在" />} />
      </Routes>
    </div>
  );
}

function isRouteSectionActive(routePath: string, pathname: string) {
  if (routePath === '/papers') return /^\/papers\/\d+/.test(pathname);
  if (routePath === '/docs') return /^\/docs\/\d+/.test(pathname);
  if (routePath === '/knowledge-spaces') return /^\/knowledge-spaces\/\d+/.test(pathname);
  return false;
}
