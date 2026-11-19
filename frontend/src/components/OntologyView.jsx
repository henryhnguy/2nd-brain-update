import React, { useCallback, useEffect, useMemo, useState } from 'react';
import {
  Network, Plus, Check, X, Trash2, Sparkles, Download, AlertTriangle, BadgeCheck,
  Link2, Quote, Search, Loader2, Save,
} from 'lucide-react';
import { api } from '../api';

const KIND_LABEL = {
  concept: 'Khái niệm', standard: 'Tiêu chuẩn', process: 'Quy trình', defect: 'Lỗi / khuyết tật',
  material: 'Vật liệu', component: 'Bộ phận', organization: 'Tổ chức', other: 'Khác',
};
const REL_LABEL = {
  is_a: 'là một loại của', part_of: 'là một phần của', related_to: 'liên quan tới', requires: 'yêu cầu',
  measured_by: 'được đo bằng', caused_by: 'gây ra bởi', supersedes: 'thay thế',
};

function StatusBadge({ status }) {
  return status === 'approved'
    ? <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-emerald-500/10 text-emerald-300 border border-emerald-500/20">Đã duyệt</span>
    : <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-amber-500/10 text-amber-300 border border-amber-500/20">Nháp</span>;
}

const inputCls = 'w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500';
const btnCls = 'inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors disabled:opacity-50';

export default function OntologyView({ documents = [] }) {
  const [terms, setTerms] = useState([]);
  const [meta, setMeta] = useState({ kinds: [], relation_kinds: [] });
  const [filter, setFilter] = useState('');
  const [query, setQuery] = useState('');
  const [mode, setMode] = useState('term'); // 'term' | 'suggest'
  const [selectedId, setSelectedId] = useState(null);
  const [term, setTerm] = useState(null);
  const [form, setForm] = useState({ name: '', kind: 'concept', definition: '', aliases: '' });
  const [msg, setMsg] = useState(null); // { type: 'ok' | 'err', text }
  const [busy, setBusy] = useState(false);
  const [notes, setNotes] = useState([]);

  const flash = (type, text) => { setMsg({ type, text }); setTimeout(() => setMsg(null), 4000); };
  const fail = (e) => flash('err', e.message || 'Có lỗi xảy ra');

  const loadTerms = useCallback(async () => {
    try { setTerms(await api.ontoTerms(filter, query)); } catch (e) { fail(e); }
  }, [filter, query]);

  const loadTerm = useCallback(async (id) => {
    try {
      const t = await api.ontoGet(id);
      setTerm(t);
      setForm({ name: t.name, kind: t.kind, definition: t.definition, aliases: t.aliases.join(', ') });
    } catch (e) { fail(e); }
  }, []);

  useEffect(() => { api.ontoMeta().then(setMeta).catch(() => {}); api.getNotes().then(setNotes).catch(() => {}); }, []);
  useEffect(() => { loadTerms(); }, [loadTerms]);
  useEffect(() => { if (selectedId) loadTerm(selectedId); else setTerm(null); }, [selectedId, loadTerm]);

  const stats = useMemo(() => ({
    approved: terms.filter((t) => t.status === 'approved').length,
    draft: terms.filter((t) => t.status === 'draft').length,
  }), [terms]);

  const parseAliases = (s) => s.split(',').map((a) => a.trim()).filter(Boolean);

  const createNew = async () => {
    const name = window.prompt('Tên thuật ngữ mới (ví dụ: AQL, Bonding gap):');
    if (!name || !name.trim()) return;
    try {
      const t = await api.ontoCreate({ name: name.trim() });
      await loadTerms();
      setMode('term');
      setSelectedId(t.id);
    } catch (e) { fail(e); }
  };

  const save = async () => {
    setBusy(true);
    try {
      const t = await api.ontoUpdate(term.id, { name: form.name, kind: form.kind, definition: form.definition, aliases: parseAliases(form.aliases) });
      setTerm(t);
      await loadTerms();
      flash('ok', 'Đã lưu');
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const toggleApprove = async () => {
    setBusy(true);
    try {
      // lưu nội dung đang soạn trước khi duyệt để định nghĩa mới nhất được duyệt
      await api.ontoUpdate(term.id, { name: form.name, kind: form.kind, definition: form.definition, aliases: parseAliases(form.aliases) });
      const t = term.status === 'approved' ? await api.ontoUnapprove(term.id) : await api.ontoApprove(term.id);
      setTerm(t);
      await loadTerms();
      flash('ok', t.status === 'approved' ? 'Đã duyệt: AI sẽ dùng thuật ngữ này' : 'Đã chuyển về nháp');
    } catch (e) { fail(e); } finally { setBusy(false); }
  };

  const remove = async () => {
    if (!window.confirm(`Xoá thuật ngữ "${term.name}" cùng quan hệ và dẫn chứng của nó?`)) return;
    try { await api.ontoDelete(term.id); setSelectedId(null); await loadTerms(); } catch (e) { fail(e); }
  };

  return (
    <div className="flex h-full min-h-0">
      {/* Danh sách thuật ngữ */}
      <div className="w-80 shrink-0 border-r border-slate-800 bg-slate-900/40 flex flex-col min-h-0">
        <div className="p-4 border-b border-slate-800 space-y-3">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-slate-100 flex items-center gap-2"><Network className="w-4 h-4 text-indigo-400" />Ontology</h2>
            <div className="flex gap-1.5">
              <a href="/api/ontology/export" target="_blank" rel="noreferrer" title="Xuất JSON" className={`${btnCls} border-slate-700 text-slate-300 hover:bg-slate-800`}><Download className="w-3.5 h-3.5" />JSON</a>
              <a href="/api/ontology/export?format=md" target="_blank" rel="noreferrer" title="Xuất Markdown" className={`${btnCls} border-slate-700 text-slate-300 hover:bg-slate-800`}>MD</a>
            </div>
          </div>
          <p className="text-[11px] leading-relaxed text-slate-500">Chỉ thuật ngữ <span className="text-emerald-300">đã duyệt</span> ảnh hưởng tới tìm kiếm, chat và Studio. Nháp thì không.</p>
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
            <input className={`${inputCls} pl-8`} placeholder="Tìm thuật ngữ..." value={query} onChange={(e) => setQuery(e.target.value)} />
          </div>
          <div className="flex gap-1.5 text-[11px]">
            {[['', `Tất cả (${stats.approved + stats.draft})`], ['approved', `Đã duyệt (${stats.approved})`], ['draft', `Nháp (${stats.draft})`]].map(([v, label]) => (
              <button key={v} onClick={() => setFilter(v)} className={`px-2 py-1 rounded-full border ${filter === v ? 'bg-indigo-600 border-indigo-500 text-white' : 'border-slate-700 text-slate-400 hover:bg-slate-800'}`}>{label}</button>
            ))}
          </div>
          <div className="flex gap-2">
            <button onClick={createNew} className={`${btnCls} flex-1 justify-center bg-indigo-600 border-indigo-500 text-white hover:bg-indigo-500`}><Plus className="w-3.5 h-3.5" />Thuật ngữ</button>
            <button onClick={() => { setMode('suggest'); setSelectedId(null); }} className={`${btnCls} flex-1 justify-center border-indigo-500/40 text-indigo-300 hover:bg-indigo-500/10`}><Sparkles className="w-3.5 h-3.5" />Gợi ý</button>
          </div>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {terms.length === 0 && <p className="text-xs text-slate-500 p-4 text-center">Chưa có thuật ngữ. Bấm “Gợi ý” để tìm ứng viên từ tài liệu, hoặc “+ Thuật ngữ” để tự thêm.</p>}
          {terms.map((t) => (
            <button key={t.id} onClick={() => { setMode('term'); setSelectedId(t.id); }}
              className={`w-full text-left p-2.5 rounded-lg border transition-colors ${selectedId === t.id && mode === 'term' ? 'bg-slate-800 border-indigo-500/50' : 'border-transparent hover:bg-slate-800/60'}`}>
              <div className="flex items-center justify-between gap-2">
                <span className="text-sm font-medium text-slate-200 truncate">{t.name}</span>
                <StatusBadge status={t.status} />
              </div>
              <div className="mt-1 flex items-center gap-2 text-[10px] text-slate-500">
                <span>{KIND_LABEL[t.kind] || t.kind}</span>
                {t.verified_evidence > 0 && <span className="flex items-center gap-0.5 text-emerald-400"><BadgeCheck className="w-3 h-3" />{t.verified_evidence}</span>}
                {t.relation_count > 0 && <span className="flex items-center gap-0.5"><Link2 className="w-3 h-3" />{t.relation_count}</span>}
              </div>
            </button>
          ))}
        </div>
      </div>

      {/* Khu soạn thảo / gợi ý */}
      <div className="flex-1 min-w-0 overflow-y-auto">
        {msg && (
          <div className={`mx-6 mt-4 px-3 py-2 rounded-lg text-xs border ${msg.type === 'ok' ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300' : 'bg-rose-500/10 border-rose-500/30 text-rose-300'}`}>{msg.text}</div>
        )}
        {mode === 'suggest' && (
          <SuggestPanel documents={documents} onDone={async (n) => { await loadTerms(); flash('ok', `Đã thêm ${n} thuật ngữ nháp`); setMode('term'); }} fail={fail} />
        )}
        {mode === 'term' && !term && (
          <div className="h-full flex items-center justify-center text-center text-slate-500 text-sm p-10">
            Chọn một thuật ngữ ở bên trái để xem, sửa và duyệt.
          </div>
        )}
        {mode === 'term' && term && (
          <TermEditor
            term={term} form={form} setForm={setForm} meta={meta} busy={busy}
            terms={terms} documents={documents} notes={notes}
            onSave={save} onToggleApprove={toggleApprove} onDelete={remove}
            reload={async () => { await loadTerm(term.id); await loadTerms(); }} fail={fail} flash={flash}
          />
        )}
      </div>
    </div>
  );
}

function TermEditor({ term, form, setForm, meta, busy, terms, documents, notes, onSave, onToggleApprove, onDelete, reload, fail, flash }) {
  const [rel, setRel] = useState({ to: '', kind: 'related_to' });
  const [ev, setEv] = useState({ source: '', quote: '' });

  const addRelation = async () => {
    if (!rel.to) return;
    try { await api.ontoAddRelation({ from_id: term.id, to_id: Number(rel.to), kind: rel.kind }); setRel({ ...rel, to: '' }); await reload(); } catch (e) { fail(e); }
  };
  const addEvidence = async () => {
    if (!ev.source || !ev.quote.trim()) return;
    const [source_type, id] = ev.source.split(':');
    try {
      const r = await api.ontoAddEvidence(term.id, { source_type, source_id: Number(id), quote: ev.quote });
      flash(r.verified ? 'ok' : 'err', r.verified ? 'Đã kiểm: câu trích có thật trong nguồn' : 'Không tìm thấy câu này trong nguồn, đã lưu dưới dạng CHƯA KIỂM');
      setEv({ source: ev.source, quote: '' });
      await reload();
    } catch (e) { fail(e); }
  };

  const others = terms.filter((t) => t.id !== term.id);
  const sourceOptions = [
    ...documents.map((d) => ({ value: `document:${d.id}`, label: `Tài liệu · ${d.filename}` })),
    ...notes.map((n) => ({ value: `note:${n.id}`, label: `Ghi chú · ${n.title}` })),
  ];

  return (
    <div className="p-6 max-w-3xl space-y-6">
      <div className="flex items-center justify-between gap-3">
        <div className="flex items-center gap-2"><h3 className="text-lg font-semibold text-slate-100">{term.name}</h3><StatusBadge status={term.status} /></div>
        <div className="flex gap-2">
          <button onClick={onSave} disabled={busy} className={`${btnCls} border-slate-700 text-slate-200 hover:bg-slate-800`}>{busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}Lưu</button>
          <button onClick={onToggleApprove} disabled={busy}
            className={`${btnCls} ${term.status === 'approved' ? 'border-amber-500/40 text-amber-300 hover:bg-amber-500/10' : 'bg-emerald-600 border-emerald-500 text-white hover:bg-emerald-500'}`}>
            <Check className="w-3.5 h-3.5" />{term.status === 'approved' ? 'Bỏ duyệt' : 'Duyệt'}
          </button>
          <button onClick={onDelete} className={`${btnCls} border-rose-500/30 text-rose-300 hover:bg-rose-500/10`}><Trash2 className="w-3.5 h-3.5" /></button>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3">
        <label className="col-span-2 text-xs text-slate-400 space-y-1">Tên chuẩn
          <input className={inputCls} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
        </label>
        <label className="text-xs text-slate-400 space-y-1">Loại
          <select className={inputCls} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value })}>
            {(meta.kinds.length ? meta.kinds : Object.keys(KIND_LABEL)).map((k) => <option key={k} value={k}>{KIND_LABEL[k] || k}</option>)}
          </select>
        </label>
      </div>
      <label className="block text-xs text-slate-400 space-y-1">Định nghĩa (AI sẽ dùng đúng nghĩa này khi thuật ngữ được đã duyệt)
        <textarea rows={4} className={inputCls} value={form.definition} onChange={(e) => setForm({ ...form, definition: e.target.value })}
          placeholder="Ví dụ: Acceptable Quality Limit: mức lỗi tối đa chấp nhận được khi lấy mẫu kiểm tra." />
      </label>
      <label className="block text-xs text-slate-400 space-y-1">Tên gọi khác (cách nhau bằng dấu phẩy): dùng để mở rộng tìm kiếm
        <input className={inputCls} value={form.aliases} onChange={(e) => setForm({ ...form, aliases: e.target.value })} placeholder="mức lấy mẫu, sampling level" />
      </label>

      {/* Quan hệ */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-slate-300 flex items-center gap-1.5"><Link2 className="w-3.5 h-3.5 text-indigo-400" />Quan hệ</h4>
        {term.relations.length === 0 && <p className="text-xs text-slate-500">Chưa có quan hệ nào.</p>}
        {term.relations.map((r) => (
          <div key={`${r.direction}-${r.id}`} className="flex items-center justify-between gap-2 text-xs bg-slate-900/60 border border-slate-800 rounded-lg px-3 py-2">
            <span className="text-slate-300">
              {r.direction === 'out'
                ? <>{term.name} <span className="text-indigo-300">{REL_LABEL[r.kind] || r.kind}</span> <b>{r.other_name}</b></>
                : <><b>{r.other_name}</b> <span className="text-indigo-300">{REL_LABEL[r.kind] || r.kind}</span> {term.name}</>}
              {r.other_status !== 'approved' && <span className="ml-2 text-[10px] text-amber-400">(đầu kia còn nháp)</span>}
            </span>
            <button onClick={async () => { await api.ontoDeleteRelation(r.id); await reload(); }} className="text-slate-500 hover:text-rose-400"><X className="w-3.5 h-3.5" /></button>
          </div>
        ))}
        <div className="flex gap-2">
          <select className={`${inputCls} w-44`} value={rel.kind} onChange={(e) => setRel({ ...rel, kind: e.target.value })}>
            {(meta.relation_kinds.length ? meta.relation_kinds : Object.keys(REL_LABEL)).map((k) => <option key={k} value={k}>{REL_LABEL[k] || k}</option>)}
          </select>
          <select className={inputCls} value={rel.to} onChange={(e) => setRel({ ...rel, to: e.target.value })}>
            <option value="">Chọn thuật ngữ...</option>
            {others.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
          <button onClick={addRelation} disabled={!rel.to} className={`${btnCls} border-slate-700 text-slate-200 hover:bg-slate-800`}><Plus className="w-3.5 h-3.5" />Nối</button>
        </div>
      </section>

      {/* Dẫn chứng */}
      <section className="space-y-2">
        <h4 className="text-xs font-semibold text-slate-300 flex items-center gap-1.5"><Quote className="w-3.5 h-3.5 text-indigo-400" />Dẫn chứng từ tài liệu</h4>
        {term.evidence.length === 0 && <p className="text-xs text-slate-500">Chưa có dẫn chứng. Dán một câu nguyên văn từ tài liệu để hệ thống kiểm tra nó có thật.</p>}
        {term.evidence.map((e) => (
          <div key={e.id} className="text-xs bg-slate-900/60 border border-slate-800 rounded-lg px-3 py-2 space-y-1">
            <div className="flex items-center justify-between gap-2">
              <span className="text-slate-400 truncate">{e.source_title}</span>
              <span className="flex items-center gap-2 shrink-0">
                {e.verified
                  ? <span className="flex items-center gap-1 text-emerald-400"><BadgeCheck className="w-3.5 h-3.5" />Đã kiểm</span>
                  : <span className="flex items-center gap-1 text-amber-400"><AlertTriangle className="w-3.5 h-3.5" />Chưa kiểm được</span>}
                <button onClick={async () => { await api.ontoDeleteEvidence(e.id); await reload(); }} className="text-slate-500 hover:text-rose-400"><X className="w-3.5 h-3.5" /></button>
              </span>
            </div>
            <p className="text-slate-300 italic">“{e.quote}”</p>
          </div>
        ))}
        <select className={inputCls} value={ev.source} onChange={(e) => setEv({ ...ev, source: e.target.value })}>
          <option value="">Chọn nguồn (tài liệu hoặc ghi chú)...</option>
          {sourceOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <textarea rows={2} className={inputCls} value={ev.quote} onChange={(e) => setEv({ ...ev, quote: e.target.value })} placeholder="Dán nguyên văn câu trong tài liệu nói về thuật ngữ này" />
        <button onClick={addEvidence} disabled={!ev.source || !ev.quote.trim()} className={`${btnCls} border-slate-700 text-slate-200 hover:bg-slate-800`}><Plus className="w-3.5 h-3.5" />Thêm dẫn chứng</button>
      </section>
    </div>
  );
}

function SuggestPanel({ documents, onDone, fail }) {
  const [loading, setLoading] = useState(false);
  const [cands, setCands] = useState(null);
  const [picked, setPicked] = useState({});
  const [minSources, setMinSources] = useState(2);
  const [adding, setAdding] = useState(false);

  const run = async () => {
    setLoading(true);
    try {
      const list = await api.ontoSuggest({ limit: 60, min_sources: minSources });
      setCands(list);
      setPicked(Object.fromEntries(list.map((c, i) => [i, false])));
    } catch (e) { fail(e); } finally { setLoading(false); }
  };

  const add = async () => {
    const chosen = cands.filter((_, i) => picked[i]);
    if (!chosen.length) return;
    setAdding(true);
    try { const r = await api.ontoAccept(chosen); await onDone(r.created); } catch (e) { fail(e); } finally { setAdding(false); }
  };

  const count = Object.values(picked).filter(Boolean).length;
  return (
    <div className="p-6 max-w-3xl space-y-4">
      <div>
        <h3 className="text-lg font-semibold text-slate-100 flex items-center gap-2"><Sparkles className="w-4 h-4 text-indigo-400" />Gợi ý thuật ngữ từ tài liệu</h3>
        <p className="text-xs text-slate-500 mt-1 leading-relaxed">
          Quét {documents.length} tài liệu và ghi chú, tìm mã/viết tắt (như AQL, QMS-FTW.06) và cụm từ viết hoa lặp lại ở nhiều nguồn. Chạy trên máy, không gọi AI.
          Mỗi gợi ý kèm một câu nguyên văn từ nguồn. Thêm vào chỉ tạo <b>nháp</b>: bạn viết định nghĩa rồi duyệt sau.
        </p>
      </div>
      <div className="flex items-center gap-3">
        <label className="text-xs text-slate-400 flex items-center gap-2">Xuất hiện ở ít nhất
          <input type="number" min={1} max={20} value={minSources} onChange={(e) => setMinSources(Math.max(1, Number(e.target.value) || 1))} className={`${inputCls} w-16`} /> nguồn
        </label>
        <button onClick={run} disabled={loading} className={`${btnCls} bg-indigo-600 border-indigo-500 text-white hover:bg-indigo-500`}>
          {loading ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Sparkles className="w-3.5 h-3.5" />}{cands ? 'Quét lại' : 'Quét tài liệu'}
        </button>
      </div>
      {cands && cands.length === 0 && <p className="text-xs text-slate-500">Không có ứng viên mới (hoặc tất cả đã là thuật ngữ). Thử giảm số nguồn tối thiểu.</p>}
      {cands && cands.length > 0 && (
        <>
          <div className="flex items-center justify-between">
            <span className="text-xs text-slate-400">{cands.length} ứng viên · đã chọn {count}</span>
            <button onClick={add} disabled={!count || adding} className={`${btnCls} bg-emerald-600 border-emerald-500 text-white hover:bg-emerald-500`}>
              {adding ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}Thêm {count} mục vào nháp
            </button>
          </div>
          <div className="space-y-2">
            {cands.map((c, i) => (
              <label key={`${c.name}-${i}`} className={`block cursor-pointer text-xs rounded-lg border px-3 py-2 ${picked[i] ? 'bg-indigo-500/10 border-indigo-500/40' : 'bg-slate-900/60 border-slate-800 hover:bg-slate-900'}`}>
                <div className="flex items-center gap-2">
                  <input type="checkbox" checked={!!picked[i]} onChange={(e) => setPicked({ ...picked, [i]: e.target.checked })} />
                  <b className="text-slate-200">{c.name}</b>
                  <span className="text-slate-500">{c.sources} nguồn · {c.count} lần</span>
                </div>
                <p className="text-slate-400 mt-1 italic line-clamp-2">“{c.quote}” <span className="not-italic text-slate-600">: {c.source_title}</span></p>
              </label>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
