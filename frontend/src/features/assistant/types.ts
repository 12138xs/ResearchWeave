export type AssistantExchange = {
  id: number;
  session: number;
  question: string;
  answer: string;
  sources: Array<Record<string, unknown>>;
  model: string;
  usage: Record<string, unknown>;
  context_warning: string;
  created_at: string;
};

export type AssistantSession = {
  id: number;
  title: string;
  mode: 'compare' | 'reproduction_checklist' | 'literature_brief' | 'freeform_scoped';
  scope_json: Record<string, unknown>;
  created_by: number | null;
  created_by_username?: string | null;
  created_at: string;
  updated_at: string;
  exchanges: AssistantExchange[];
};
