export type ResearchMapPayload = {
  root: Record<string, unknown>;
  children: Array<Record<string, unknown>>;
  relations: Array<Record<string, unknown>>;
  snapshot: Record<string, unknown> | null;
};
