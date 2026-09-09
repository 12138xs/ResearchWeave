import { apiFetch, payloadMessage, readResponsePayload } from './client';

export async function submitMaterial(url: string, data: FormData | object) {
  const response = await apiFetch(url, data instanceof FormData
    ? { method: 'POST', body: data }
    : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data) });
  const payload = await readResponsePayload(response);
  if (!response.ok) throw new Error(payloadMessage(payload, '操作失败，请稍后重试。'));
  return payload;
}

