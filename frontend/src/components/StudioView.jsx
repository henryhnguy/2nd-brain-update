import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {
  AlertTriangle, Check, ChevronDown, ChevronUp, ClipboardList, Copy, Download, FileText,
  GraduationCap, Layers, Loader2, Plus, RefreshCw, Save, Trash2, ArrowLeft, Wand2,
} from 'lucide-react';
import { api } from '../api';

const KIND_ICONS = { lesson: GraduationCap, sop: ClipboardList, synthesis: Layers };
const STATUS_LABEL = {
  draft: 'Nháp', questions: 'Đang hỏi bổ sung', outline: 'Có dàn ý', writing: 'Đang viết',
  written: 'Đã viết xong', reviewed: 'Đã rà soát',
};
const PARA = ['Projects', 'Areas', 'Resources', 'Archives'];

const mdComponents = {
  h1: (p) => <h1 className="text-2xl font-bold text-slate-100 pb-2 border-b border-slate-800 mb-4" {...p} />,
  h2: (p) => <h2 className="text-lg font-semibold text-slate-200 mt-6 mb-2" {...p} />,
  h3: (p) => <h3 className="text-base font-medium text-slate-300 mt-4 mb-2" {...p} />,
  p: (p) => <p className="text-slate-300 leading-relaxed mb-3 text-sm" {...p} />,
  ul: (p) => <ul className="list-disc pl-5 space-y-1 text-slate-300 text-sm mb-3" {...p} />,
  ol: (p) => <ol className="list-decimal pl-5 space-y-1 text-slate-300 text-sm mb-3" {...p} />,
  blockquote: (p) => <blockquote className="border-l-4 border-indigo-500 pl-4 py-1 text-slate-400 bg-indigo-950/20 rounded-r my-3 text-sm" {...p} />,
  table: (p) => <div className="overflow-x-auto mb-4"><table className="min-w-full text-xs border border-slate-800" {...p} /></div>,
  th: (p) => <th className="border border-slate-800 bg-slate-900 px-2 py-1.5 text-left text-slate-200 font-semibold" {...p} />,
  td: (p) => <td className="border border-slate-800 px-2 py-1.5 text-slate-300 align-top" {...p} />,
};

function Markdown({ children }) {
  return <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>{children || ''}</ReactMarkdown>;
}

const btn = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium transition-colors disabled:opacity-50';
const btnPrimary = `${btn} bg-indigo-600 hover:bg-indigo-500 text-white`;
const btnGhost = `${btn} bg-slate-800 hover:bg-slate-700 text-slate-200`;
const inputCls = 'w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500';

function Banner({ tone = 'warn', children }) {
  const cls = tone === 'error'
    ? 'border-rose-500/30 bg-rose-500/10 text-rose-200'
    : 'border-amber-500/30 bg-amber-500/10 text-amber-200';
  return (
    <div className={`flex items-start gap-2 p-3 rounded-xl border text-xs ${cls}`}>
      <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
      <div className="min-w-0 break-words">{children}</div>
    </div>
  );
}

// ---------------------------------------------------------------- generic form
function ParamsForm({ fields, values, onChange }) {
  return (
    <div className="space-y-3">
      {fields.map((f) => (
        <div key={f.key} className="space-y-1">
          <label className="text-xs font-semibold text-slate-200">
            {f.label}{f.required && <span className="text-rose-400"> *</span>}
          </label>
          {f.type === 'textarea' ? (
            <textarea rows={3} className={inputCls} placeholder={f.placeholder} value={values[f.key] || ''}
              onChange={(e) => onChange({ ...values, [f.key]: e.target.value })} />
          ) : f.type === 'select' ? (
            <select className={inputCls} value={values[f.key] || ''}
              onChange={(e) => onChange({ ...values, [f.key]: e.target.value })}>
              <option value="">— chọn —</option>
              {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
            </select>
          ) : (
            <input type={f.type === 'number' ? 'number' : 'text'} className={inputCls} placeholder={f.placeholder}
              value={values[f.key] || ''} onChange={(e) => onChange({ ...values, [f.key]: e.target.value })} />
          )}
        </div>
      ))}
    </div>
  );
}

function ScopePicker({ scope, onChange }) {
  const cats = scope.categories || [];
  const toggle = (c) => onChange({ ...scope, categories: cats.includes(c) ? cats.filter((x) => x !== c) : [...cats, c] });
  return (
    <div className="space-y-2">
      <label className="text-xs font-semibold text-slate-200">Nguồn kiến thức được dùng</label>
      <p className="text-[10px] text-slate-500">Để trống = toàn bộ kho. Chọn nhóm PARA hoặc gắn thẻ để giới hạn phạm vi.</p>
      <div className="flex flex-wrap gap-2">
        {PARA.map((c) => (
          <button key={c} type="button" onClick={() => toggle(c)}
            className={`px-2.5 py-1 rounded-full text-[11px] border ${cats.includes(c)
              ? 'bg-indigo-600/20 border-indigo-500/60 text-indigo-200' : 'border-slate-800 text-slate-400 hover:border-slate-700'}`}>
            {c}
          </button>
        ))}
      </div>
      <input className={inputCls} placeholder="Thẻ (tag), cách nhau bằng dấu phẩy. VD: qc, bonding"
        value={(scope.tags || []).join(', ')}
        onChange={(e) => onChange({ ...scope, tags: e.target.value.split(',').map((t) => t.trim()).filter(Boolean) })} />
    </div>
  );
}

// ------------------------------------------------------------------------ main
export default function StudioView() {
  const [kinds, setKinds] = useState(null);
  const [docs, setDocs] = useState([]);
  const [doc, setDoc] = useState(null);
  const [creating, setCreating] = useState(null); // kind id while the "new" form is open
  const [form, setForm] = useState({});
  const [scope, setScope] = useState({});
  const [step, setStep] = useState(0);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [drafts, setDrafts] = useState({}); // unsaved text edits, per section id / question id

  const loadList = useCallback(async () => {
    try { setDocs(await api.studioList()); } catch (e) { setError(e.message); }
  }, []);

  useEffect(() => {
    api.studioKinds().then(setKinds).catch((e) => setError(e.message));
    loadList();
  }, [loadList]);

  const kind = doc && kinds ? kinds[doc.kind] : null;
  const stepKeys = useMemo(() => {
    if (!doc) return [];
    return doc.kind === 'sop'
      ? ['input', 'questions', 'outline', 'write', 'finish']
      : ['input', 'outline', 'write', 'finish'];
  }, [doc]);

  const defaultStep = useCallback((d) => {
    const keys = d.kind === 'sop' ? ['input', 'questions', 'outline', 'write', 'finish'] : ['input', 'outline', 'write', 'finish'];
    const pick = (k) => keys.indexOf(k);
    if (d.status === 'written' || d.status === 'reviewed') return pick('finish');
    if (d.outline.length) {
      const any = Object.values(d.sections || {}).some((s) => (s.content || '').trim());
      return any || d.status === 'writing' ? pick('write') : pick('outline');
    }
    if (d.kind === 'sop' && d.questions.length) return pick('questions');
    return 0;
  }, []);

  const openDoc = useCallback(async (id) => {
    setError('');
    try {
      const d = await api.studioGet(id);
      setDoc(d); setStep(defaultStep(d)); setDrafts({}); setCreating(null);
    } catch (e) { setError(e.message); }
  }, [defaultStep]);

  // Poll while a background "write all" job runs
  const pollRef = useRef(null);
  useEffect(() => {
    if (!doc?.job?.running) return undefined;
    pollRef.current = setInterval(async () => {
      try { setDoc(await api.studioGet(doc.id)); } catch { /* keep last state */ }
    }, 1500);
    return () => clearInterval(pollRef.current);
  }, [doc?.id, doc?.job?.running]);

  const run = async (label, fn, after) => {
    setBusy(label); setError('');
    try {
      const d = await fn();
      if (d && d.id) setDoc(d);
      if (after) after(d);
    } catch (e) { setError(e.message); }
    setBusy('');
  };

  const sectionText = (sid) => drafts[sid] ?? doc.sections[sid]?.content ?? '';
  const dirtyIds = doc ? Object.keys(drafts).filter((k) => doc.sections[k] && drafts[k] !== (doc.sections[k].content || '')) : [];
  const saveDrafts = async () => {
    const patch = {};
    dirtyIds.forEach((sid) => { patch.sections = { ...(patch.sections || {}), [sid]: drafts[sid] }; });
    if (!patch.sections) return doc;
    const d = await api.studioPatch(doc.id, patch);
    setDrafts({});
    return d;
  };

  // ------------------------------------------------------------- create flow
  const startCreate = (k) => {
    setCreating(k); setForm({}); setScope({}); setDoc(null); setError('');
  };
  const submitCreate = () => run('create', () => api.studioCreate(creating, form, scope), async (d) => {
    setCreating(null); setStep(0); setDrafts({}); loadList();
    await goNext(d);
  });

  // First action after creating: questions (SOP) or outline (others)
  const goNext = async (d) => {
    setBusy('gen'); setError('');
    try {
      const out = d.kind === 'sop' ? await api.studioQuestions(d.id) : await api.studioOutline(d.id);
      setDoc(out); setStep(1); loadList();
    } catch (e) {
      setDoc(await api.studioGet(d.id)); setError(e.message);
    }
    setBusy('');
  };

  // ---------------------------------------------------------------- panels
  const renderInput = () => (
    <div className="space-y-4 max-w-2xl">
      <ParamsForm fields={kind.fields} values={doc.params}
        onChange={(v) => setDoc({ ...doc, params: v })} />
      <ScopePicker scope={doc.scope || {}} onChange={(s) => setDoc({ ...doc, scope: s })} />
      <div className="flex gap-2">
        <button className={btnPrimary} disabled={!!busy}
          onClick={() => run('gen', async () => {
            await api.studioPatch(doc.id, { params: doc.params, scope: doc.scope });
            return doc.kind === 'sop' ? api.studioQuestions(doc.id) : api.studioOutline(doc.id);
          }, () => setStep(1))}>
          {busy === 'gen' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
          {doc.kind === 'sop' ? 'Tạo câu hỏi bổ sung' : 'Tạo dàn ý'}
        </button>
        {doc.outline.length > 0 && (
          <button className={btnGhost} onClick={() => setStep(stepKeys.indexOf('outline'))}>Giữ dàn ý hiện tại →</button>
        )}
      </div>
      {busy === 'gen' && <p className="text-[11px] text-slate-500">AI đang đọc kho kiến thức của bạn, có thể mất 10–60 giây…</p>}
    </div>
  );

  const renderQuestions = () => (
    <div className="space-y-4 max-w-2xl">
      <p className="text-xs text-slate-400">
        AI chỉ hỏi những thông tin còn thiếu để SOP không bị đoán mò. Trả lời càng cụ thể, SOP càng chính xác.
        Câu nào để trống sẽ thành chỗ <span className="font-mono text-amber-300">⚠️ [CẦN BỔ SUNG]</span> trong SOP.
      </p>
      {doc.questions.length === 0 && <Banner>Chưa có câu hỏi. Bạn có thể bỏ qua bước này.</Banner>}
      {doc.questions.map((q) => (
        <div key={q.id} className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
          <div className="text-xs font-semibold text-slate-100">{q.question}</div>
          {q.why && <div className="text-[10px] text-slate-500">Vì sao hỏi: {q.why}</div>}
          <textarea rows={2} className={inputCls} value={drafts[q.id] ?? q.answer ?? ''}
            onChange={(e) => setDrafts({ ...drafts, [q.id]: e.target.value })} placeholder="Câu trả lời của bạn…" />
        </div>
      ))}
      <div className="flex gap-2">
        <button className={btnPrimary} disabled={!!busy}
          onClick={() => run('outline', async () => {
            const answers = {};
            doc.questions.forEach((q) => { if (drafts[q.id] !== undefined) answers[q.id] = drafts[q.id]; });
            if (Object.keys(answers).length) await api.studioPatch(doc.id, { answers });
            setDrafts({});
            return api.studioOutline(doc.id);
          }, () => setStep(2))}>
          {busy === 'outline' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
          Lưu câu trả lời & tạo dàn ý
        </button>
        <button className={btnGhost} disabled={!!busy}
          onClick={() => run('q', () => api.studioQuestions(doc.id))}>
          <RefreshCw className="w-3.5 h-3.5" /> Hỏi lại
        </button>
      </div>
    </div>
  );

  const moveItem = (i, dir) => {
    const o = [...doc.outline]; const j = i + dir;
    if (j < 0 || j >= o.length) return;
    [o[i], o[j]] = [o[j], o[i]];
    setDoc({ ...doc, outline: o });
  };
  const editItem = (i, patch) => setDoc({ ...doc, outline: doc.outline.map((o, k) => (k === i ? { ...o, ...patch } : o)) });

  const renderOutline = () => (
    <div className="space-y-4 max-w-3xl">
      <p className="text-xs text-slate-400">
        Chỉnh dàn ý trước khi viết: đổi tên, sắp xếp lại, thêm hoặc bớt mục.
        {doc.kind === 'synthesis' && ' Số trong ngoặc là các nguồn [n] sẽ được dùng cho mục đó.'}
      </p>
      {doc.warnings?.map((w, i) => <Banner key={i}>{w}</Banner>)}
      {doc.outline.map((o, i) => (
        <div key={o.id} className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
          <div className="flex items-center gap-2">
            <span className="text-[10px] font-mono text-slate-500 w-5">{i + 1}.</span>
            <input className={inputCls} value={o.title} onChange={(e) => editItem(i, { title: e.target.value })} />
            <button className={btnGhost} onClick={() => moveItem(i, -1)} disabled={i === 0}><ChevronUp className="w-3.5 h-3.5" /></button>
            <button className={btnGhost} onClick={() => moveItem(i, 1)} disabled={i === doc.outline.length - 1}><ChevronDown className="w-3.5 h-3.5" /></button>
            <button className={btnGhost} onClick={() => setDoc({ ...doc, outline: doc.outline.filter((_, k) => k !== i) })}>
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
          <textarea rows={2} className={inputCls} value={o.brief || ''} onChange={(e) => editItem(i, { brief: e.target.value })} />
          {o.sources?.length > 0 && (
            <div className="text-[10px] text-slate-500">Nguồn dùng: {o.sources.map((n) => `[${n}]`).join(' ')}</div>
          )}
        </div>
      ))}
      {doc.kind === 'synthesis' && doc.sources.length > 0 && (
        <details className="text-xs text-slate-400">
          <summary className="cursor-pointer">Các nguồn đã chọn ({doc.sources.length})</summary>
          <ul className="mt-2 space-y-1">
            {doc.sources.map((s) => <li key={s.n}>[{s.n}] {s.title} ({s.source_type === 'document' ? 'tài liệu' : 'ghi chú'})</li>)}
          </ul>
        </details>
      )}
      <div className="flex flex-wrap gap-2">
        <button className={btnGhost} onClick={() => setDoc({ ...doc, outline: [...doc.outline, { id: `new${doc.outline.length}`, title: 'Mục mới', brief: '' }] })}>
          <Plus className="w-3.5 h-3.5" /> Thêm mục
        </button>
        <button className={btnPrimary} disabled={!!busy || !doc.outline.length}
          onClick={() => run('write', async () => {
            await api.studioPatch(doc.id, { outline: doc.outline });
            const r = await api.studioWriteAll(doc.id, false);
            return r;
          }, () => setStep(stepKeys.indexOf('write')))}>
          {busy === 'write' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
          Lưu dàn ý & viết toàn bộ
        </button>
        {doc.kind !== 'sop' && (
          <button className={btnGhost} disabled={!!busy}
            onClick={() => window.confirm('Tạo lại dàn ý sẽ xóa nội dung đã viết. Tiếp tục?') && run('gen', () => api.studioOutline(doc.id))}>
            <RefreshCw className="w-3.5 h-3.5" /> Tạo lại dàn ý
          </button>
        )}
      </div>
    </div>
  );

  const renderWrite = () => {
    const job = doc.job || {};
    const pct = job.total ? Math.round((100 * job.done) / job.total) : 0;
    return (
      <div className="space-y-4 max-w-3xl">
        {job.running && (
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-1.5">
            <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden"><div className="h-full bg-indigo-500 transition-all" style={{ width: `${Math.max(pct, 4)}%` }} /></div>
            <div className="text-[11px] text-slate-400">Đang viết {job.done}/{job.total}{job.current ? ` — “${job.current}”` : ''}…</div>
          </div>
        )}
        {!job.running && job.errors?.length > 0 && (
          <Banner tone="error">
            {job.errors.map((e, i) => <div key={i}><b>{e.section}:</b> {e.error}</div>)}
          </Banner>
        )}
        <div className="flex flex-wrap gap-2">
          <button className={btnPrimary} disabled={!!busy || job.running}
            onClick={() => run('w', async () => { await saveDrafts(); return api.studioWriteAll(doc.id, false); })}>
            <Wand2 className="w-3.5 h-3.5" /> Viết các mục còn thiếu
          </button>
          <button className={btnGhost} disabled={!!busy || job.running}
            onClick={() => window.confirm('Viết lại TẤT CẢ các mục, kể cả mục bạn đã sửa tay?') && run('w', () => api.studioWriteAll(doc.id, true))}>
            <RefreshCw className="w-3.5 h-3.5" /> Viết lại tất cả
          </button>
          <button className={btnGhost} disabled={!dirtyIds.length || !!busy} onClick={() => run('save', saveDrafts)}>
            <Save className="w-3.5 h-3.5" /> Lưu chỉnh sửa{dirtyIds.length ? ` (${dirtyIds.length})` : ''}
          </button>
          <button className={btnGhost} onClick={() => setStep(stepKeys.indexOf('finish'))}>Sang bước cuối →</button>
        </div>
        {doc.outline.map((o) => {
          const sec = doc.sections[o.id] || {};
          return (
            <div key={o.id} className="rounded-xl bg-slate-950 border border-slate-800 overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 border-b border-slate-800">
                <div className="text-xs font-semibold text-slate-100">{o.title}</div>
                <div className="flex items-center gap-2">
                  <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${sec.status === 'done' ? 'bg-emerald-500/15 text-emerald-300'
                    : sec.status === 'error' ? 'bg-rose-500/15 text-rose-300' : 'bg-slate-800 text-slate-400'}`}>
                    {sec.status === 'done' ? (sec.edited ? 'đã sửa tay' : 'xong') : sec.status === 'error' ? 'lỗi' : 'chưa viết'}
                  </span>
                  <button className={btnGhost} disabled={!!busy || job.running}
                    onClick={() => run(`s-${o.id}`, () => api.studioWriteSection(doc.id, o.id))}>
                    {busy === `s-${o.id}` ? <Loader2 className="w-3 h-3 animate-spin" /> : <RefreshCw className="w-3 h-3" />} Viết lại mục
                  </button>
                </div>
              </div>
              {sec.error && <div className="px-3 pt-2 text-[10px] text-rose-300">{sec.error}</div>}
              <textarea rows={Math.min(14, Math.max(4, sectionText(o.id).split('\n').length + 1))}
                className="w-full bg-transparent px-3 py-2 text-xs text-slate-200 font-mono focus:outline-none resize-y"
                placeholder="(chưa có nội dung)" value={sectionText(o.id)}
                onChange={(e) => setDrafts({ ...drafts, [o.id]: e.target.value })} />
            </div>
          );
        })}
      </div>
    );
  };

  const [noteCategory, setNoteCategory] = useState('Resources');
  const [versionLabel, setVersionLabel] = useState('');
  const [bump, setBump] = useState('minor');
  const [viewVersion, setViewVersion] = useState(null);
  const [savedNote, setSavedNote] = useState(null);

  const download = async () => {
    const m = await api.studioMarkdown(doc.id);
    const url = URL.createObjectURL(new Blob([m.markdown], { type: 'text/markdown;charset=utf-8' }));
    const a = document.createElement('a'); a.href = url; a.download = m.filename; a.click(); URL.revokeObjectURL(url);
  };

  const renderFinish = () => {
    const q = doc.quality || {};
    const hasQ = doc.kind !== 'sop' && q.total_paragraphs !== undefined;
    return (
      <div className="space-y-4 max-w-3xl">
        <div className="flex flex-wrap gap-2">
          <button className={btnPrimary} disabled={!!busy} onClick={() => run('review', async () => { await saveDrafts(); return api.studioReview(doc.id); })}>
            {busy === 'review' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
            {doc.kind === 'sop' ? 'Rà soát SOP' : 'Kiểm tra nguồn trích dẫn'}
          </button>
          <button className={btnGhost} onClick={download}><Download className="w-3.5 h-3.5" /> Tải .md</button>
          <button className={btnGhost} onClick={() => navigator.clipboard?.writeText(doc.markdown)}><Copy className="w-3.5 h-3.5" /> Sao chép</button>
          <button className={btnGhost} onClick={() => setStep(stepKeys.indexOf('write'))}>← Quay lại chỉnh sửa</button>
        </div>

        {hasQ && (
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
            <div className="text-xs font-semibold text-slate-100">
              Kiểm tra nguồn: {Math.round((q.coverage ?? 1) * 100)}% đoạn có trích dẫn ({q.cited_paragraphs}/{q.total_paragraphs})
            </div>
            {q.invalid_citations?.length > 0 && (
              <Banner tone="error">Trích dẫn không tồn tại trong danh sách nguồn: {q.invalid_citations.map((n) => `[${n}]`).join(' ')}. Có thể AI bịa nguồn, hãy sửa hoặc viết lại mục đó.</Banner>
            )}
            {q.uncited_paragraphs?.length > 0 && (
              <div className="space-y-1">
                <div className="text-[11px] text-amber-300">Các đoạn chưa có trích dẫn cần bạn kiểm chứng:</div>
                {q.uncited_paragraphs.map((u, i) => (
                  <div key={i} className="text-[11px] text-slate-400"><b className="text-slate-300">{u.section}:</b> {u.excerpt}…</div>
                ))}
              </div>
            )}
            {!q.invalid_citations?.length && !q.uncited_paragraphs?.length && <div className="text-[11px] text-emerald-300">Mọi đoạn đều có trích dẫn hợp lệ.</div>}
          </div>
        )}

        {doc.kind === 'sop' && doc.review?.length > 0 && (
          <div className="space-y-2">
            <div className="text-xs font-semibold text-slate-100">Kết quả rà soát ({doc.review.length})</div>
            {doc.review.map((f, i) => (
              <div key={i} className="p-2.5 rounded-xl bg-slate-950 border border-slate-800 text-[11px] space-y-0.5">
                <div className="flex items-center gap-2">
                  <span className={`px-1.5 py-0.5 rounded-full text-[10px] ${f.severity === 'high' ? 'bg-rose-500/15 text-rose-300' : f.severity === 'medium' ? 'bg-amber-500/15 text-amber-300' : 'bg-slate-800 text-slate-400'}`}>{f.severity}</span>
                  <span className="text-slate-300 font-semibold">{f.section}</span>
                </div>
                <div className="text-slate-300">{f.issue}</div>
                {f.suggestion && <div className="text-slate-500">→ {f.suggestion}</div>}
              </div>
            ))}
          </div>
        )}

        {doc.kind === 'sop' && (
          <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
            <div className="text-xs font-semibold text-slate-100">Phiên bản SOP (hiện tại: {doc.version})</div>
            <div className="flex flex-wrap gap-2">
              <input className={`${inputCls} flex-1 min-w-[180px]`} placeholder="Nội dung thay đổi, VD: Bổ sung bước 3"
                value={versionLabel} onChange={(e) => setVersionLabel(e.target.value)} />
              <select className={`${inputCls} !w-auto`} value={bump} onChange={(e) => setBump(e.target.value)}>
                <option value="minor">Sửa nhỏ (1.0 → 1.1)</option><option value="major">Thay đổi lớn (1.x → 2.0)</option>
              </select>
              <button className={btnPrimary} disabled={!!busy}
                onClick={() => run('ver', async () => { await saveDrafts(); const d = await api.studioVersion(doc.id, versionLabel, bump); setVersionLabel(''); return d; })}>
                <Save className="w-3.5 h-3.5" /> Lưu phiên bản
              </button>
            </div>
            {doc.versions?.length > 0 && (
              <ul className="text-[11px] text-slate-400 space-y-1">
                {doc.versions.map((v) => (
                  <li key={v.id}>
                    <button className="text-indigo-300 hover:underline" onClick={async () => setViewVersion(await api.studioGetVersion(doc.id, v.version))}>v{v.version}</button>
                    {' '}· {v.created_at.slice(0, 10)} · {v.label || '—'}
                  </li>
                ))}
              </ul>
            )}
            {viewVersion && (
              <div className="border-t border-slate-800 pt-2">
                <div className="flex justify-between text-[10px] text-slate-500 mb-1"><span>Đang xem bản v{viewVersion.version} (chỉ đọc)</span><button onClick={() => setViewVersion(null)}>Đóng</button></div>
                <div className="max-h-80 overflow-y-auto"><Markdown>{viewVersion.markdown}</Markdown></div>
              </div>
            )}
          </div>
        )}

        <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
          <div className="text-xs font-semibold text-slate-100">Lưu vào kho ghi chú</div>
          <div className="flex flex-wrap gap-2 items-center">
            <select className={`${inputCls} !w-auto`} value={noteCategory} onChange={(e) => setNoteCategory(e.target.value)}>
              {PARA.map((c) => <option key={c}>{c}</option>)}
            </select>
            <button className={btnPrimary} disabled={!!busy}
              onClick={() => run('note', async () => { await saveDrafts(); const r = await api.studioSaveNote(doc.id, noteCategory); setSavedNote(r); return api.studioGet(doc.id); })}>
              <FileText className="w-3.5 h-3.5" /> {doc.note_id ? 'Cập nhật ghi chú' : 'Lưu thành ghi chú'}
            </button>
            {savedNote && <span className="text-[11px] text-emerald-300">✓ {savedNote.updated ? 'Đã cập nhật' : 'Đã tạo'} ghi chú #{savedNote.note_id} (đã index để tìm kiếm)</span>}
          </div>
        </div>

        <div className="rounded-xl border border-slate-800 p-5 bg-slate-950/50"><Markdown>{doc.markdown}</Markdown></div>
      </div>
    );
  };

  const panels = { input: renderInput, questions: renderQuestions, outline: renderOutline, write: renderWrite, finish: renderFinish };

  // ----------------------------------------------------------------- layout
  return (
    <div className="flex-1 flex h-screen overflow-hidden">
      <aside className="w-72 border-r border-slate-800 bg-slate-950/60 flex flex-col">
        <div className="p-4 border-b border-slate-800">
          <div className="text-sm font-bold text-slate-100 flex items-center gap-2"><Wand2 className="w-4 h-4 text-indigo-400" /> Studio</div>
          <p className="text-[10px] text-slate-500 mt-1">Soạn bài học, SOP và tài liệu tổng hợp từ kho kiến thức của bạn.</p>
        </div>
        <div className="p-3 space-y-1.5 border-b border-slate-800">
          {kinds && Object.values(kinds).map((k) => {
            const Icon = KIND_ICONS[k.id] || FileText;
            return (
              <button key={k.id} onClick={() => startCreate(k.id)}
                className="w-full flex items-center gap-2 px-3 py-2 rounded-lg text-xs text-slate-200 bg-slate-900 hover:bg-slate-800 text-left">
                <Icon className="w-3.5 h-3.5 text-indigo-400" /> <span className="flex-1">{k.label}</span><Plus className="w-3 h-3 text-slate-500" />
              </button>
            );
          })}
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {docs.length === 0 && <p className="text-[11px] text-slate-600 p-2">Chưa có tài liệu nào.</p>}
          {docs.map((d) => {
            const Icon = KIND_ICONS[d.kind] || FileText;
            return (
              <div key={d.id} className={`group flex items-start gap-2 p-2 rounded-lg cursor-pointer ${doc?.id === d.id ? 'bg-indigo-600/15' : 'hover:bg-slate-900'}`}
                onClick={() => openDoc(d.id)}>
                <Icon className="w-3.5 h-3.5 mt-0.5 text-slate-400 shrink-0" />
                <div className="min-w-0 flex-1">
                  <div className="text-xs text-slate-200 truncate">{d.title}</div>
                  <div className="text-[10px] text-slate-500">{STATUS_LABEL[d.status] || d.status} · {d.updated_at.slice(0, 10)}</div>
                </div>
                <button className="opacity-0 group-hover:opacity-100 text-slate-500 hover:text-rose-400"
                  onClick={async (e) => {
                    e.stopPropagation();
                    if (!window.confirm(`Xóa “${d.title}”?`)) return;
                    await api.studioDelete(d.id); if (doc?.id === d.id) setDoc(null); loadList();
                  }}><Trash2 className="w-3 h-3" /></button>
              </div>
            );
          })}
        </div>
      </aside>

      <section className="flex-1 overflow-y-auto p-6">
        {error && <div className="mb-4 max-w-3xl"><Banner tone="error">{error}</Banner></div>}

        {!doc && !creating && (
          <div className="max-w-2xl space-y-3 text-slate-400 text-sm">
            <h2 className="text-lg font-semibold text-slate-100">Chọn loại tài liệu để bắt đầu</h2>
            {kinds && Object.values(kinds).map((k) => {
              const Icon = KIND_ICONS[k.id] || FileText;
              return (
                <button key={k.id} onClick={() => startCreate(k.id)}
                  className="w-full text-left p-4 rounded-2xl border border-slate-800 bg-slate-950 hover:border-indigo-500/50 transition-colors">
                  <div className="flex items-center gap-2 text-slate-100 font-semibold text-sm"><Icon className="w-4 h-4 text-indigo-400" /> {k.label}</div>
                  <p className="text-xs text-slate-400 mt-1">{k.description}</p>
                  <p className="text-[10px] text-slate-600 mt-1">{k.steps.join(' → ')}</p>
                </button>
              );
            })}
          </div>
        )}

        {creating && kinds && (
          <div className="max-w-2xl space-y-4">
            <button className="text-xs text-slate-400 flex items-center gap-1" onClick={() => setCreating(null)}><ArrowLeft className="w-3 h-3" /> Quay lại</button>
            <h2 className="text-lg font-semibold text-slate-100">Tạo {kinds[creating].label.toLowerCase()} mới</h2>
            <ParamsForm fields={kinds[creating].fields} values={form} onChange={setForm} />
            <ScopePicker scope={scope} onChange={setScope} />
            <button className={btnPrimary} disabled={!!busy} onClick={submitCreate}>
              {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
              {kinds[creating].id === 'sop' ? 'Tạo & hỏi thông tin còn thiếu' : 'Tạo & lập dàn ý'}
            </button>
            {busy && <p className="text-[11px] text-slate-500">AI đang đọc kho kiến thức của bạn, có thể mất 10–60 giây…</p>}
          </div>
        )}

        {doc && kind && (
          <div className="space-y-5">
            <div>
              <input className="bg-transparent text-xl font-bold text-slate-100 w-full max-w-3xl focus:outline-none border-b border-transparent focus:border-slate-700"
                value={doc.title} onChange={(e) => setDoc({ ...doc, title: e.target.value })}
                onBlur={() => api.studioPatch(doc.id, { title: doc.title }).then(loadList).catch((e) => setError(e.message))} />
              <div className="text-[11px] text-slate-500 mt-1">{kind.label} · {STATUS_LABEL[doc.status] || doc.status}</div>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {kind.steps.map((label, i) => (
                <button key={label} onClick={() => setStep(i)}
                  className={`px-3 py-1 rounded-full text-[11px] border ${step === i ? 'bg-indigo-600/20 border-indigo-500/60 text-indigo-200' : 'border-slate-800 text-slate-400 hover:border-slate-700'}`}>
                  {i + 1}. {label}
                </button>
              ))}
            </div>
            {panels[stepKeys[step]]?.()}
          </div>
        )}
      </section>
    </div>
  );
}
