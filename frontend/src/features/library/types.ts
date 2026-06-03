export type CatalogStats = {
  papers: number;
  documents: number;
  knowledge_spaces: number;
  keywords: string[];
  status_counts: Record<string, number>;
};

export type KeywordEntry = {
  name: string;
  aliases: string[];
  paper_count: number;
  document_count: number;
  total_count: number;
  source: string;
};

export type KeywordSuggestion = {
  name: string;
  aliases?: string[];
  paper_count: number;
  document_count?: number;
  total_count: number;
};

export type KnowledgeSpace = {
  id: number;
  name: string;
  slug: string;
  kind: string;
  description: string;
  parent_id: number | null;
  order: number;
  is_active: boolean;
  path?: string;
  depth?: number;
  descendant_count?: number;
};
