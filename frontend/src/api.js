const API_BASE = '/api';

// Studio requests: JSON in/out, errors carry the server's human-readable `detail`
async function studioReq(path, { method = 'GET', body } = {}) {
  const res = await fetch(`${API_BASE}${path}`, {
    method,
    headers: body ? { 'Content-Type': 'application/json' } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* empty body */ }
  if (!res.ok) throw new Error(data?.detail || `Lỗi ${res.status}`);
  return data;
}

export const api = {
  // Notes
  getNotes: async (category = '', tag = '', q = '') => {
    const params = new URLSearchParams();
    if (category && category !== 'All') params.append('category', category);
    if (tag) params.append('tag', tag);
    if (q) params.append('q', q);
    const res = await fetch(`${API_BASE}/notes?${params.toString()}`);
    return res.json();
  },
  getNote: async (id) => {
    const res = await fetch(`${API_BASE}/notes/${id}`);
    return res.json();
  },
  createNote: async (note) => {
    const res = await fetch(`${API_BASE}/notes`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(note)
    });
    return res.json();
  },
  updateNote: async (id, note) => {
    const res = await fetch(`${API_BASE}/notes/${id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(note)
    });
    return res.json();
  },
  deleteNote: async (id) => {
    const res = await fetch(`${API_BASE}/notes/${id}`, { method: 'DELETE' });
    return res.json();
  },
  getCategories: async () => {
    const res = await fetch(`${API_BASE}/notes/meta/categories`);
    return res.json();
  },
  getTags: async () => {
    const res = await fetch(`${API_BASE}/notes/meta/tags`);
    return res.json();
  },

  // Documents
  getDocuments: async () => {
    const res = await fetch(`${API_BASE}/documents`);
    return res.json();
  },
  uploadDocument: async (file) => {
    const formData = new FormData();
    formData.append('file', file);
    const res = await fetch(`${API_BASE}/documents/upload`, {
      method: 'POST',
      body: formData
    });
    return res.json();
  },
  deleteDocument: async (id) => {
    const res = await fetch(`${API_BASE}/documents/${id}`, { method: 'DELETE' });
    return res.json();
  },

  // Chat & RAG
  getSessions: async () => {
    const res = await fetch(`${API_BASE}/chat/sessions`);
    return res.json();
  },
  createSession: async (title = 'Hội thoại mới') => {
    const res = await fetch(`${API_BASE}/chat/sessions?title=${encodeURIComponent(title)}`, {
      method: 'POST'
    });
    return res.json();
  },
  deleteSession: async (id) => {
    const res = await fetch(`${API_BASE}/chat/sessions/${id}`, { method: 'DELETE' });
    return res.json();
  },
  getMessages: async (sessionId) => {
    const res = await fetch(`${API_BASE}/chat/sessions/${sessionId}/messages`);
    return res.json();
  },
  askQuery: async (sessionId, question, provider = null, model = null) => {
    const payload = { session_id: sessionId, question };
    if (provider) payload.provider = provider;
    if (model) payload.model = model;
    const res = await fetch(`${API_BASE}/chat/query`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    return res.json();
  },

  // Search
  search: async (q, limit = 10, sourceType = null) => {
    const params = new URLSearchParams({ q, limit });
    if (sourceType) params.append('source_type', sourceType);
    const res = await fetch(`${API_BASE}/search?${params.toString()}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || `Lỗi tìm kiếm (${res.status})`);
    // Embedding down: the server falls back to keyword search and explains why in a header
    const warning = res.headers.get('X-Search-Warning');
    if (warning) data.warning = decodeURIComponent(warning);
    return data;
  },

  // Settings
  getSettings: async () => {
    const res = await fetch(`${API_BASE}/settings`);
    return res.json();
  },
  updateSettings: async (settings) => {
    const res = await fetch(`${API_BASE}/settings`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(settings)
    });
    return res.json();
  },

  // Live chat-model lists
  models: async (provider, refresh = false) => {
    const res = await fetch(`${API_BASE}/settings/models?provider=${provider}&refresh=${refresh}`);
    const data = await res.json();
    if (!res.ok) throw new Error(data?.detail || 'Không lấy được danh sách model');
    return data;
  },

  // Embedding
  embeddingStatus: async () => {
    const res = await fetch(`${API_BASE}/settings/embedding/status`);
    return res.json();
  },
  embeddingTest: async () => {
    const res = await fetch(`${API_BASE}/settings/embedding/test`, { method: 'POST' });
    return res.json();
  },
  embeddingReindex: async (all = false) => {
    const res = await fetch(`${API_BASE}/settings/embedding/reindex?all=${all}`, { method: 'POST' });
    return res.json();
  },
  // ---- Studio (lesson / SOP / synthesis) ----
  studioKinds: () => studioReq('/studio/kinds'),
  studioList: () => studioReq('/studio/docs'),
  studioCreate: (kind, params, scope) => studioReq('/studio/docs', { method: 'POST', body: { kind, params, scope } }),
  studioGet: (id) => studioReq(`/studio/docs/${id}`),
  studioDelete: (id) => studioReq(`/studio/docs/${id}`, { method: 'DELETE' }),
  studioPatch: (id, patch) => studioReq(`/studio/docs/${id}`, { method: 'PATCH', body: patch }),
  studioQuestions: (id) => studioReq(`/studio/docs/${id}/questions`, { method: 'POST' }),
  studioOutline: (id) => studioReq(`/studio/docs/${id}/outline`, { method: 'POST' }),
  studioWriteSection: (id, sid) => studioReq(`/studio/docs/${id}/sections/${sid}/write`, { method: 'POST' }),
  studioWriteAll: (id, all = false) => studioReq(`/studio/docs/${id}/write`, { method: 'POST', body: { all } }),
  studioReview: (id) => studioReq(`/studio/docs/${id}/review`, { method: 'POST' }),
  studioVersion: (id, label, bump) => studioReq(`/studio/docs/${id}/versions`, { method: 'POST', body: { label, bump } }),
  studioGetVersion: (id, version) => studioReq(`/studio/docs/${id}/versions/${encodeURIComponent(version)}`),
  studioMarkdown: (id) => studioReq(`/studio/docs/${id}/markdown`),
  studioSaveNote: (id, category, tags = []) => studioReq(`/studio/docs/${id}/save-note`, { method: 'POST', body: { category, tags } }),
};
