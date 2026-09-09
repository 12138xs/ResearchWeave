import type { TaskItem } from '../tasks/types';

export type ExperimentProject = {
  id: number;
  title: string;
  slug: string;
  paper: number | null;
  paper_title?: string | null;
  document: number | null;
  document_title?: string | null;
  space: number | null;
  space_path?: string | null;
  status: 'planned' | 'running' | 'completed' | 'blocked' | 'archived';
  owner: number | null;
  visibility: 'private' | 'team';
  can_edit: boolean;
  owner_username?: string | null;
  objective: string;
  protocol_markdown: string;
  repo_url: string;
  environment_json: Record<string, unknown>;
  runs?: ExperimentRun[];
  created_at: string;
  updated_at: string;
};

export type ExperimentRun = {
  id: number;
  project: number;
  status: 'planned' | 'running' | 'success' | 'failed' | 'cancelled';
  params_json: Record<string, unknown>;
  metrics_json: Record<string, unknown>;
  artifact_keys: string[];
  notes: string;
  started_at: string | null;
  finished_at: string | null;
  created_by: number | null;
  created_by_username?: string | null;
  created_at: string;
  updated_at: string;
};

export type ExperimentListResponse = {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  results: ExperimentProject[];
};

export type ExperimentExecuteResponse = {
  run: ExperimentRun;
  task: TaskItem;
};
