export type SearchIndexEntry = {
  id: number;
  object_type: 'paper' | 'document' | 'experiment';
  object_id: number;
  title: string;
  summary: string;
  space_id: number | null;
  keywords_json: string[];
  source_updated_at: string;
  indexed_at: string;
  url: string;
};

export type SearchResponse = {
  count: number;
  next: string | null;
  previous: string | null;
  results: SearchIndexEntry[];
};
