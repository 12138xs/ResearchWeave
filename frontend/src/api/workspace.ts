import { apiFetch, payloadMessage, readResponsePayload } from './client';

export type PersonalProfile = { style: string; memory_enabled: boolean };
export type PersonalEntry = { id: number; kind: 'memory' | 'note'; title: string; body: string; enabled: boolean; status: 'planned' | 'observed' | 'concluded'; source_session: number | null; updated_at: string };
export type Publication = { id: number; title: string; body: string; evidence_ids: number[]; can_delete: boolean };

export function newRequestId() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (char) => {
    const value = crypto.getRandomValues(new Uint8Array(1))[0] & 15;
    return (char === 'x' ? value : ((value & 3) | 8)).toString(16);
  });
}
export async function workspaceRequest<T>(path: string, method = 'GET', payload?: object): Promise<T> {
  const response = await apiFetch(`/api/assistant/${path}`, {
    method, ...(payload ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) } : {}),
  });
  const data = await readResponsePayload(response);
  if (!response.ok) throw new Error(payloadMessage(data, '个人工作区操作失败。'));
  return data as T;
}
