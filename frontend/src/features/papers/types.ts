import type { KeywordSuggestion } from '../library/types';
import type { TaskItem } from '../tasks/types';

export type PaperLightProfile = {
  id: number;
  version?: number;
  generator: string;
  keywords: string[];
  background: string;
  method: string;
  results: string;
  source_text_preview?: string;
  created_at?: string;
};

export type PaperDeepProfile = {
  id: number;
  version: number;
  is_active: boolean;
  parser_name: string;
  summary: string;
  sections: Array<Record<string, unknown>>;
  figures: Array<Record<string, unknown>>;
  formulas: Array<Record<string, unknown>>;
  code_suggestions: Array<Record<string, unknown>>;
  reproduction_notes: string;
  created_at?: string;
};

export type Paper = {
  id: number;
  code?: string;
  title: string;
  slug: string;
  authors: string[];
  publication_type: string;
  year: number | null;
  venue: string;
  volume: string;
  issue: string;
  pages: string;
  area: string;
  abstract: string;
  doi: string;
  arxiv_id: string;
  source_url: string;
  status: string;
  code_status: string;
  space: string | null;
  space_id?: number | null;
  space_slug?: string | null;
  space_path?: string | null;
  keywords: string[];
  light_profile: PaperLightProfile | null;
  deep_profile: PaperDeepProfile | null;
  active_deep_task: TaskItem | null;
  has_pdf: boolean;
  reading_state?: PaperReadingState | null;
  created_at?: string;
  updated_at: string;
};

export type PaperReadingState = {
  id: number;
  paper: number;
  reading_status: 'unread' | 'skimmed' | 'deep_reading' | 'discussed' | 'adopted' | 'rejected';
  reproduction_status: 'unknown' | 'not_applicable' | 'planned' | 'in_progress' | 'reproduced' | 'failed';
  owner: number | null;
  owner_username: string | null;
  next_step: string;
  due_at: string | null;
  updated_by: number | null;
  updated_by_username: string | null;
  created_at: string;
  updated_at: string;
};

export type ReadingReview = {
  id: number;
  paper: number;
  profile_type: 'light' | 'deep';
  profile_id: number;
  status: 'needs_review' | 'approved' | 'rejected';
  score: number | null;
  notes: string;
  reviewed_by: number | null;
  reviewed_by_username: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type PaperQaSource = {
  id: number;
  title: string;
  year: number | null;
  venue: string;
  keywords: string[];
  used_sections: string[];
  profile_version: number | null;
};

export type PaperQaResponse = {
  answer: string;
  model: string;
  usage: Record<string, number>;
  mode: 'compressed' | 'preview';
  requested_mode?: 'compressed' | 'preview';
  context_warning?: string;
  estimated_context_tokens?: number;
  context_token_limit?: number;
  sources: PaperQaSource[];
};

export type PaperQaHistoryItem = {
  id: number;
  paper: number;
  username: string;
  question: string;
  answer: string;
  mode: 'compressed' | 'preview';
  model: string;
  usage: Record<string, number>;
  sources: PaperQaSource[];
  context_warning: string;
  created_at: string;
};

export type PaperQaHistoryResponse = {
  count: number;
  results: PaperQaHistoryItem[];
};

export type PaperMetadataCandidate = {
  title?: string;
  authors?: string[];
  year?: number | null;
  venue?: string;
  doi?: string;
  arxiv_id?: string;
  source_url?: string;
  abstract?: string;
  keywords?: string[];
  raw?: string;
  confidence?: number;
  source?: string;
  notes?: string;
};

export type PaperMetadataSuggestion = {
  provider: string;
  applied: boolean;
  suggestions: Partial<PaperMetadataCandidate> & {
    confidence?: number;
    notes?: string;
  };
  evidence: Array<{ title: string; url: string; snippet: string }>;
  candidates?: PaperMetadataCandidate[];
};

export type PaperReferenceImportResponse = {
  count: number;
  candidates: PaperMetadataCandidate[];
};

export type PaperMetadataForm = {
  title: string;
  authors: string;
  publication_type: string;
  year: string;
  venue: string;
  volume: string;
  issue: string;
  pages: string;
  area: string;
  abstract: string;
  doi: string;
  arxiv_id: string;
  source_url: string;
  code_status: string;
  keywords: string;
};

export type PaperSearchResponse = {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  results: Paper[];
  related_keywords: KeywordSuggestion[];
  hot_keywords: KeywordSuggestion[];
  years: number[];
};

export type PaperDeepProfileListResponse = {
  active: PaperDeepProfile | null;
  results: PaperDeepProfile[];
};
