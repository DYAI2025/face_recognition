// Thin client for the local Face2AI API (see api/routes.py). Frames are sent as raw
// image/jpeg bodies; enrollment parameters travel as query parameters. Errors carry the
// server's `detail` text and HTTP status so the UI can show the real reason.

export async function getStatus() {
  return jsonFetch('/api/status');
}

export async function listIdentities() {
  return jsonFetch('/api/identities');
}

export async function deleteIdentity(id) {
  return jsonFetch(`/api/identities/${encodeURIComponent(id)}`, { method: 'DELETE' });
}

export async function eraseAll() {
  return jsonFetch('/api/identities', { method: 'DELETE' });
}

export async function recognize(blob) {
  return imageFetch('/api/recognize', blob);
}

export async function enroll(blob, name, consent) {
  const qs = new URLSearchParams({ display_name: name, consent: consent ? 'true' : 'false' });
  return imageFetch(`/api/enroll?${qs}`, blob);
}

async function imageFetch(url, blob) {
  const response = await fetch(url, {
    method: 'POST',
    headers: { 'content-type': 'image/jpeg' },
    body: blob,
  });
  if (!response.ok) throw await apiError(response);
  return response.json();
}

async function jsonFetch(url, init) {
  const response = await fetch(url, { cache: 'no-store', ...init });
  if (!response.ok) throw await apiError(response);
  return response.status === 204 ? null : response.json();
}

async function apiError(response) {
  let detail = `HTTP ${response.status}`;
  try {
    const body = await response.json();
    if (typeof body.detail === 'string') detail = body.detail;
    else if (Array.isArray(body.detail)) detail = body.detail.map((d) => d.msg || JSON.stringify(d)).join('; ');
  } catch {
    // Non-JSON error body: keep the HTTP status text.
  }
  const error = new Error(detail);
  error.status = response.status;
  return error;
}
