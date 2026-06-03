import { apiFetch, readResponsePayload } from './client';

export function uploadImage(formData: FormData) {
  return apiFetch('/api/storage/upload-image/', {
    method: 'POST',
    body: formData,
  }).then(readResponsePayload);
}
