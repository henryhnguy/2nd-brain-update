import React, { useCallback, useEffect, useState } from 'react';
import { Plus, Trash2, Check, Loader2, RefreshCw, Zap, Server, Eye, EyeOff, AlertTriangle, X } from 'lucide-react';
import { api } from '../api';

const field = 'w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500';
const EMPTY = { id: null, name: '', base_url: '', api_key: '', models: [], default_model: '', json_mode: 'auto', has_key: false };

/**
 * Quản lý provider AI tùy chỉnh (chuẩn OpenAI). Lưu/xoá/kiểm tra có hiệu lực ngay (không cần bấm "Lưu cài đặt").
 * Riêng "Đặt làm mặc định" chỉ đổi lựa chọn trong hộp thoại; nó được lưu khi bấm "Lưu cài đặt" như Gemini/OpenRouter.
 */
export default function CustomProvidersPanel({ llmProvider, onSetDefault, onChanged }) {
  const [providers, setProviders] = useState([]);
  const [presets, setPresets] = useState([]);
  const [form, setForm] = useState(null); // null = đang xem danh sách
  const [modelInput, setModelInput] = useState('');
  const [showKey, setShowKey] = useState(false);
  const [busy, setBusy] = useState('');
  const [msg, setMsg] = useState(null);
  const [testResult, setTestResult] = useState({});

  const say = (type, text) => { setMsg({ type, text }); setTimeout(() => setMsg(null), 5000); };

  const load = useCallback(async () => {
    try {
      const r = await api.customProviders();
      setProviders(r.providers || []);
      setPresets(r.presets || []);
    } catch (e) { say('err', e.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const startNew = (preset) => {
    setForm({ ...EMPTY, name: preset?.name?.replace(/\s*\(.*\)$/, '') || '', base_url: preset?.base_url || '',
      models: preset?.example_model ? [preset.example_model] : [], default_model: preset?.example_model || '' });
    setModelInput(''); setShowKey(false);
  };
  const startEdit = (p) => { setForm({ ...p, api_key: '' }); setModelInput(''); setShowKey(false); };

  const addModels = () => {
    const ids = modelInput.split(/[\n,]+/).map((s) => s.trim()).filter(Boolean);
    if (!ids.length) return;
    const merged = [...new Set([...form.models, ...ids])];
    setForm({ ...form, models: merged, default_model: form.default_model || merged[0] });
    setModelInput('');
  };
  const removeModel = (id) => {
    const models = form.models.filter((m) => m !== id);
    setForm({ ...form, models, default_model: form.default_model === id ? (models[0] || '') : form.default_model });
  };

  const fetchLive = async () => {
    if (!form.id) { say('err', 'Hãy lưu provider trước, rồi bấm lấy danh sách model.'); return; }
    setBusy('fetch');
    try {
      const r = await api.models(`custom:${form.id}`, true);
      if (r.source !== 'live') { say('err', r.error || 'Máy chủ không có danh sách model, hãy nhập ID model thủ công.'); return; }
      const merged = [...new Set([...form.models, ...r.models.map((m) => m.id)])];
      setForm({ ...form, models: merged, default_model: form.default_model || merged[0] });
      say('ok', `Đã lấy ${r.models.length} model từ máy chủ. Bấm “Lưu provider” để giữ lại.`);
    } catch (e) { say('err', e.message); } finally { setBusy(''); }
  };

  const save = async () => {
    setBusy('save');
    try {
      const body = { id: form.id, name: form.name, base_url: form.base_url, models: form.models,
        default_model: form.default_model, json_mode: form.json_mode,
        api_key: form.api_key === '' && form.has_key ? undefined : form.api_key };
      const saved = await api.saveCustomProvider(body);
      setForm(null);
      await load();
      onChanged?.();
      say('ok', `Đã lưu “${saved.name}”. Bấm “Kiểm tra kết nối” để thử.`);
    } catch (e) { say('err', e.message); } finally { setBusy(''); }
  };

  const remove = async (p) => {
    if (!window.confirm(`Xoá provider “${p.name}”?`)) return;
    try { await api.deleteCustomProvider(p.id); await load(); onChanged?.(); } catch (e) { say('err', e.message); }
  };

  const test = async (p) => {
    setBusy(`test-${p.id}`);
    setTestResult((t) => ({ ...t, [p.id]: null }));
    try { const r = await api.testCustomProvider(p.id); setTestResult((t) => ({ ...t, [p.id]: r })); }
    catch (e) { setTestResult((t) => ({ ...t, [p.id]: { ok: false, error: e.message } })); }
    finally { setBusy(''); }
  };

  const banner = msg && (
    <div className={`px-3 py-2 rounded-lg text-[11px] border ${msg.type === 'ok' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-rose-500/10 border-rose-500/30 text-rose-300'}`}>{msg.text}</div>
  );

  if (form) {
    return (
      <div className="space-y-4">
        {banner}
        <div className="flex items-center justify-between">
          <h3 className="text-xs font-bold text-slate-100">{form.id ? `Sửa “${form.name}”` : 'Thêm provider tùy chỉnh'}</h3>
          <button type="button" onClick={() => setForm(null)} className="text-slate-400 hover:text-white"><X className="w-4 h-4" /></button>
        </div>

        <label className="block space-y-1 text-[11px] text-slate-400">Tên hiển thị
          <input className={field} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} placeholder="NVIDIA NIM" />
        </label>
        <label className="block space-y-1 text-[11px] text-slate-400">Base URL (chuẩn OpenAI, thường kết thúc bằng /v1)
          <input className={field} value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })} placeholder="https://integrate.api.nvidia.com/v1" />
        </label>
        <label className="block space-y-1 text-[11px] text-slate-400">
          API key {form.has_key && <span className="text-emerald-400">(đã lưu: {form.key_masked}, để trống = giữ nguyên)</span>}
          <div className="relative">
            <input className={`${field} pr-9`} type={showKey ? 'text' : 'password'} value={form.api_key}
              onChange={(e) => setForm({ ...form, api_key: e.target.value })} placeholder={form.has_key ? '••••••••' : 'Bỏ trống nếu chạy trên máy (Ollama, LM Studio)'} />
            <button type="button" onClick={() => setShowKey(!showKey)} className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300">
              {showKey ? <EyeOff className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
            </button>
          </div>
        </label>

        <div className="space-y-2">
          <div className="flex items-center justify-between">
            <span className="text-[11px] text-slate-400">Model ({form.models.length})</span>
            <button type="button" onClick={fetchLive} disabled={busy === 'fetch'} className="text-[11px] text-indigo-400 hover:underline flex items-center gap-1 disabled:opacity-50">
              {busy === 'fetch' ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />}Lấy danh sách model từ máy chủ
            </button>
          </div>
          <div className="flex gap-2">
            <input className={field} value={modelInput} onChange={(e) => setModelInput(e.target.value)}
              onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); addModels(); } }}
              placeholder="Nhập ID model rồi Enter (nhiều model: cách nhau dấu phẩy)" />
            <button type="button" onClick={addModels} className="px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs"><Plus className="w-3.5 h-3.5" /></button>
          </div>
          <div className="max-h-40 overflow-y-auto space-y-1 pr-1">
            {form.models.length === 0 && <p className="text-[11px] text-slate-500">Chưa có model nào.</p>}
            {form.models.map((m) => (
              <div key={m} className="flex items-center justify-between gap-2 bg-slate-950 border border-slate-800 rounded-lg px-2.5 py-1.5 text-[11px]">
                <label className="flex items-center gap-2 min-w-0 cursor-pointer">
                  <input type="radio" name="default-model" checked={form.default_model === m} onChange={() => setForm({ ...form, default_model: m })} />
                  <span className="text-slate-200 truncate">{m}</span>
                  {form.default_model === m && <span className="text-[9px] text-indigo-300 shrink-0">mặc định</span>}
                </label>
                <button type="button" onClick={() => removeModel(m)} className="text-slate-500 hover:text-rose-400 shrink-0"><X className="w-3.5 h-3.5" /></button>
              </div>
            ))}
          </div>
        </div>

        <label className="flex items-start gap-2 text-[11px] text-slate-400 cursor-pointer">
          <input type="checkbox" className="mt-0.5" checked={form.json_mode === 'off'} onChange={(e) => setForm({ ...form, json_mode: e.target.checked ? 'off' : 'auto' })} />
          <span>Máy chủ không hỗ trợ chế độ JSON (<code>response_format</code>): tắt nếu Studio báo lỗi khi tạo dàn ý</span>
        </label>

        <div className="flex gap-2 pt-1">
          <button type="button" onClick={save} disabled={busy === 'save'} className="flex-1 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold disabled:opacity-50 flex items-center justify-center gap-1.5">
            {busy === 'save' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}Lưu provider
          </button>
          <button type="button" onClick={() => setForm(null)} className="px-4 py-2 rounded-xl border border-slate-700 text-slate-300 hover:bg-slate-800 text-xs">Huỷ</button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {banner}
      <p className="text-[11px] leading-relaxed text-slate-500">
        Thêm bất kỳ máy chủ AI nào nói chuẩn OpenAI (<code>/chat/completions</code>): NVIDIA NIM, DeepSeek, Groq, Ollama, LM Studio, vLLM...
        Model của provider sẽ xuất hiện trong ô chọn model ở AI Copilot và được Studio dùng khi đặt làm mặc định.
      </p>

      {providers.length === 0 && (
        <div className="text-center text-xs text-slate-500 border border-dashed border-slate-800 rounded-xl p-6">Chưa có provider tùy chỉnh nào.</div>
      )}
      {providers.map((p) => {
        const ref = `custom:${p.id}`;
        const t = testResult[p.id];
        return (
          <div key={p.id} className="border border-slate-800 bg-slate-950/60 rounded-xl p-3 space-y-2">
            <div className="flex items-start justify-between gap-2">
              <div className="min-w-0">
                <div className="flex items-center gap-2 text-xs font-semibold text-slate-100"><Server className="w-3.5 h-3.5 text-indigo-400 shrink-0" /><span className="truncate">{p.name}</span>
                  {llmProvider === ref && <span className="text-[9px] px-1.5 rounded-full bg-indigo-500/20 text-indigo-300 font-mono">Mặc định</span>}</div>
                <p className="text-[10px] text-slate-500 truncate mt-0.5">{p.base_url} · {p.models.length} model · mặc định: {p.default_model}{p.has_key ? '' : ' · không dùng key'}</p>
              </div>
              <div className="flex gap-1 shrink-0">
                <button type="button" onClick={() => startEdit(p)} className="px-2 py-1 text-[11px] rounded-lg border border-slate-700 text-slate-300 hover:bg-slate-800">Sửa</button>
                <button type="button" onClick={() => remove(p)} className="p-1.5 rounded-lg border border-rose-500/30 text-rose-300 hover:bg-rose-500/10"><Trash2 className="w-3.5 h-3.5" /></button>
              </div>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" onClick={() => test(p)} disabled={busy === `test-${p.id}`} className="px-2.5 py-1 text-[11px] rounded-lg border border-slate-700 text-slate-200 hover:bg-slate-800 flex items-center gap-1 disabled:opacity-50">
                {busy === `test-${p.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <Zap className="w-3 h-3 text-amber-300" />}Kiểm tra kết nối
              </button>
              <button type="button" onClick={() => onSetDefault(ref)} disabled={llmProvider === ref}
                className={`px-2.5 py-1 text-[11px] rounded-lg ${llmProvider === ref ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/40 cursor-default' : 'bg-indigo-600 text-white hover:bg-indigo-500'}`}>
                {llmProvider === ref ? '✓ Đang là mặc định' : 'Đặt làm mặc định'}
              </button>
            </div>
            {t && (
              <div className={`text-[11px] rounded-lg px-2.5 py-1.5 border flex items-start gap-1.5 ${t.ok ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-rose-500/10 border-rose-500/30 text-rose-300'}`}>
                {t.ok ? <Check className="w-3.5 h-3.5 shrink-0 mt-0.5" /> : <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />}
                <span>{t.ok ? `Kết nối tốt: ${t.model} trả lời “${t.reply}” trong ${t.latency_ms} ms` : t.error}</span>
              </div>
            )}
          </div>
        );
      })}

      <div className="space-y-2">
        <button type="button" onClick={() => startNew(null)} className="w-full py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-semibold flex items-center justify-center gap-1.5"><Plus className="w-3.5 h-3.5" />Thêm provider tùy chỉnh</button>
        <div className="flex flex-wrap gap-1.5 items-center text-[10px] text-slate-500">
          <span>Điền nhanh:</span>
          {presets.map((p) => (
            <button key={p.name} type="button" onClick={() => startNew(p)} className="px-2 py-0.5 rounded-full border border-slate-700 text-slate-300 hover:bg-slate-800">{p.name}</button>
          ))}
        </div>
      </div>
    </div>
  );
}
