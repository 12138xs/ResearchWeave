export type Doc = {
  id: number;
  code?: string;
  title: string;
  slug: string;
  summary: string;
  status: string;
  space: string | null;
  space_id?: number | null;
  space_slug?: string | null;
  space_path?: string | null;
  keywords: string[];
  markdown?: string;
  current_version?: number | null;
  updated_at: string;
};

export type DocumentListResponse = {
  count: number;
  page: number;
  page_size: number;
  total_pages: number;
  results: Doc[];
};

export type UploadedImage = {
  name: string;
  url: string;
  markdown: string;
};
