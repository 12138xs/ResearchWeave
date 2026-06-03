import type { TaskItem } from '../tasks/types';

export type QualityIssue = {
  id: number;
  object_type: string;
  object_id: number;
  dimension: 'metadata' | 'ai_output' | 'reproduction' | 'document' | 'search_index';
  severity: 'low' | 'medium' | 'high';
  status: 'open' | 'acknowledged' | 'resolved' | 'dismissed';
  score: number | null;
  notes: string;
  evidence_json: Record<string, unknown>;
  source_task: number | null;
  reviewed_by: number | null;
  reviewed_by_username: string | null;
  reviewed_at: string | null;
  created_at: string;
  updated_at: string;
};

export type QualityAuditResponse = {
  task: TaskItem;
};
