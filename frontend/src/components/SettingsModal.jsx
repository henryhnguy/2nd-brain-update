import React, { useState, useEffect } from 'react';
import { X, Key, Check, Database, Cpu, ExternalLink, ShieldCheck, Globe, Sparkles, Layers, RefreshCw, AlertTriangle, Server } from 'lucide-react';
import CustomProvidersPanel from './CustomProvidersPanel';
import { api } from '../api';
import { useModelCatalog } from '../useModelCatalog';

export default function SettingsModal({ isOpen, onClose, settings, onSaveSettings, onRefreshSettings }) {
  const [activeTab, setActiveTab] = useState('gemini'); // 'gemini' | 'openrouter' | 'custom' | 'embedding'
  const [llmProvider, setLlmProvider] = useState('gemini');
  
  // Gemini
  const [geminiApiKey, setGeminiApiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState('gemini-2.5-flash');

  // OpenRouter
  const [openrouterApiKey, setOpenrouterApiKey] = useState('');
  const [openrouterModel, setOpenrouterModel] = useState('deepseek/deepseek-chat');
  const [customModelInput, setCustomModelInput] = useState('');
  const [isCustomModel, setIsCustomModel] = useState(false);

  // Embedding
  const [embProvider, setEmbProvider] = useState('auto');
  const [embGeminiModel, setEmbGeminiModel] = useState('gemini-embedding-001');
  const [embLocalModel, setEmbLocalModel] = useState('intfloat/multilingual-e5-large');
  const [embStatus, setEmbStatus] = useState(null);
  const [embTest, setEmbTest] = useState(null);
  const [embBusy, setEmbBusy] = useState('');
  const [orFilter, setOrFilter] = useState('');
  const [geminiOtherModel, setGeminiOtherModel] = useState('');
  const geminiCatalog = useModelCatalog('gemini', isOpen && activeTab === 'gemini');
  const orCatalog = useModelCatalog('openrouter', isOpen && activeTab === 'openrouter');

  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (settings) {
      setLlmProvider(settings.llm_provider || 'gemini');
      setActiveTab((t) => (t === 'embedding' || t === 'custom' ? t : (settings.llm_provider || 'gemini').startsWith('custom:') ? 'custom' : settings.llm_provider || 'gemini'));
      if (settings.embedding) {
        setEmbStatus(settings.embedding);
        setEmbProvider(settings.embedding.configured_provider || 'auto');
        setEmbGeminiModel(settings.embedding.gemini_model || 'gemini-embedding-001');
        setEmbLocalModel(settings.embedding.local_model || 'intfloat/multilingual-e5-large');
      }
      setGeminiModel(settings.gemini_model || settings.model_name || 'gemini-2.5-flash');
      
      const orModel = settings.openrouter_model || 'deepseek/deepseek-chat';
      setOpenrouterModel(orModel);
      
      const knownIds = (settings.available_models?.openrouter || []).map(m => m.id);
      if (knownIds.length > 0 && !knownIds.includes(orModel)) {
        setIsCustomModel(true);
        setCustomModelInput(orModel);
      } else {
        setIsCustomModel(false);
      }
    }
  }, [settings]);

  // Poll embedding status while the tab is open and a re-index is running
  const reindexRunning = !!embStatus?.reindex?.running;
  useEffect(() => {
    if (!isOpen || activeTab !== 'embedding') return undefined;
    let cancelled = false;
    const tick = async () => {
      try {
        const st = await api.embeddingStatus();
        if (!cancelled) setEmbStatus(st);
      } catch { /* server restarting; keep last status */ }
    };
    tick();
    if (!reindexRunning) return () => { cancelled = true; };
    const id = setInterval(tick, 1500);
    return () => { cancelled = true; clearInterval(id); };
  }, [isOpen, activeTab, reindexRunning]);

  if (!isOpen) return null;

  const runEmbTest = async () => {
    setEmbBusy('test');
    setEmbTest(null);
    try {
      // apply the current selection first so the test reflects what is on screen
      await onSaveSettings({
        embedding_provider: embProvider,
        embedding_gemini_model: embGeminiModel,
        embedding_local_model: embLocalModel,
        gemini_api_key: geminiApiKey ? geminiApiKey.trim() : undefined,
      });
      setEmbTest(await api.embeddingTest());
      setEmbStatus(await api.embeddingStatus());
    } catch (err) {
      setEmbTest({ ok: false, error: err.message });
    }
    setEmbBusy('');
  };

  const runReindex = async (all) => {
    setEmbBusy('reindex');
    try {
      const r = await api.embeddingReindex(all);
      setEmbStatus(r);
    } catch { /* ignore */ }
    setEmbBusy('');
  };

  const handleSave = async () => {
    setIsSaving(true);
    const finalOpenrouterModel = isCustomModel && customModelInput.trim() ? customModelInput.trim() : openrouterModel;

    await onSaveSettings({
      llm_provider: llmProvider,
      gemini_api_key: geminiApiKey ? geminiApiKey.trim() : undefined,
      openrouter_api_key: openrouterApiKey ? openrouterApiKey.trim() : undefined,
      gemini_model: geminiModel,
      openrouter_model: finalOpenrouterModel,
      model_name: geminiModel,
      embedding_provider: embProvider,
      embedding_gemini_model: embGeminiModel,
      embedding_local_model: embLocalModel
    });

    setIsSaving(false);
    setSaved(true);
    setTimeout(() => {
      setSaved(false);
      onClose();
    }, 1200);
  };

  const orAll = orCatalog.models || settings?.available_models?.openrouter || [];
  const orQuery = orFilter.trim().toLowerCase();
  const openrouterPresets = (orQuery
    ? orAll.filter((m) => `${m.id} ${m.name}`.toLowerCase().includes(orQuery))
    : orAll
  ).slice(0, 300);
  if (!isCustomModel && openrouterModel && !openrouterPresets.some((m) => m.id === openrouterModel)) {
    const cur = orAll.find((m) => m.id === openrouterModel);
    openrouterPresets.unshift(cur || { id: openrouterModel, name: openrouterModel, desc: 'đang lưu' });
  }
  const geminiChatModels = [...(geminiCatalog.models || settings?.available_models?.gemini || [])];
  if (geminiModel && !geminiChatModels.some((m) => m.id === geminiModel)) {
    geminiChatModels.unshift({ id: geminiModel, name: geminiModel, desc: 'đang lưu' });
  }

  return (
    <div className="fixed inset-0 z-50 bg-black/70 backdrop-blur-sm flex items-center justify-center p-4">
      <div className="bg-slate-900 border border-slate-800 rounded-2xl w-full max-w-lg overflow-hidden shadow-2xl flex flex-col max-h-[90vh]">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center space-x-2">
            <Cpu className="w-4 h-4 text-indigo-400" />
            <h2 className="text-sm font-bold text-slate-100">Cài đặt AI Model & Nhà cung cấp</h2>
          </div>
          <button
            onClick={onClose}
            className="p-1 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Provider Switch Tabs */}
        <div className="px-6 pt-4 border-b border-slate-800 bg-slate-950/40">
          <div className="flex space-x-2">
            <button
              onClick={() => setActiveTab('gemini')}
              className={`flex items-center space-x-2 pb-3 px-3 text-xs font-semibold border-b-2 transition-all ${
                activeTab === 'gemini'
                  ? 'border-indigo-500 text-indigo-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>Google Gemini</span>
              {llmProvider === 'gemini' && (
                <span className="text-[9px] px-1.5 py-0.2 rounded-full bg-indigo-500/20 text-indigo-300 font-mono">
                  Mặc định
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('openrouter')}
              className={`flex items-center space-x-2 pb-3 px-3 text-xs font-semibold border-b-2 transition-all ${
                activeTab === 'openrouter'
                  ? 'border-indigo-500 text-indigo-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Globe className="w-3.5 h-3.5" />
              <span>OpenRouter (Claude, DeepSeek, GPT...)</span>
              {llmProvider === 'openrouter' && (
                <span className="text-[9px] px-1.5 py-0.2 rounded-full bg-emerald-500/20 text-emerald-300 font-mono">
                  Mặc định
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('custom')}
              className={`flex items-center space-x-2 pb-3 px-3 text-xs font-semibold border-b-2 transition-all ${
                activeTab === 'custom'
                  ? 'border-indigo-500 text-indigo-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Server className="w-3.5 h-3.5" />
              <span>Tùy chỉnh</span>
              {llmProvider.startsWith('custom:') && (
                <span className="text-[9px] px-1.5 py-0.2 rounded-full bg-violet-500/20 text-violet-300 font-mono">
                  Mặc định
                </span>
              )}
            </button>

            <button
              onClick={() => setActiveTab('embedding')}
              className={`flex items-center space-x-2 pb-3 px-3 text-xs font-semibold border-b-2 transition-all ${
                activeTab === 'embedding'
                  ? 'border-indigo-500 text-indigo-400'
                  : 'border-transparent text-slate-400 hover:text-slate-200'
              }`}
            >
              <Layers className="w-3.5 h-3.5" />
              <span>Embedding</span>
              {embStatus?.quality === 'weak' && (
                <span className="w-1.5 h-1.5 rounded-full bg-amber-400" title="Đang dùng embedding yếu" />
              )}
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="p-6 overflow-y-auto space-y-5 flex-1">
          {/* Active Provider Selector */}
          {activeTab !== 'embedding' && activeTab !== 'custom' && (
          <div className="p-3 bg-slate-950 border border-slate-800 rounded-xl flex items-center justify-between">
            <div className="text-xs">
              <span className="text-slate-400">Nhà cung cấp AI mặc định: </span>
              <span className="font-semibold text-slate-200 uppercase">
                {llmProvider === 'gemini' ? 'Google Gemini' : llmProvider === 'openrouter' ? 'OpenRouter' : ((settings?.custom_providers || []).find((p) => `custom:${p.id}` === llmProvider)?.name || 'Tùy chỉnh')}
              </span>
            </div>
            <button
              type="button"
              onClick={() => setLlmProvider(activeTab)}
              className={`px-3 py-1 rounded-lg text-xs font-medium transition-colors ${
                llmProvider === activeTab
                  ? 'bg-indigo-600/30 text-indigo-300 border border-indigo-500/40 cursor-default'
                  : 'bg-indigo-600 text-white hover:bg-indigo-500'
              }`}
            >
              {llmProvider === activeTab ? '✓ Đang là mặc định' : `Đặt ${activeTab === 'gemini' ? 'Gemini' : 'OpenRouter'} làm mặc định`}
            </button>
          </div>
          )}

          {/* Gemini Tab Settings */}
          {activeTab === 'gemini' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-200 flex items-center space-x-1.5">
                    <Key className="w-3.5 h-3.5 text-indigo-400" />
                    <span>Google Gemini API Key</span>
                  </label>
                  <a
                    href="https://aistudio.google.com/app/apikey"
                    target="_blank"
                    rel="noreferrer"
                    className="text-[10px] text-indigo-400 hover:underline flex items-center space-x-0.5"
                  >
                    <span>Lấy key Google miễn phí</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                </div>

                <input
                  type="password"
                  value={geminiApiKey}
                  onChange={(e) => setGeminiApiKey(e.target.value)}
                  placeholder={
                    settings?.gemini_api_key_configured
                      ? `Đã cấu hình (${settings.gemini_api_key_masked})`
                      : 'Dán AIzaSy... vào đây'
                  }
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                />
                {settings?.gemini_api_key_configured && !geminiApiKey && (
                  <p className="text-[10px] text-emerald-400 flex items-center space-x-1">
                    <ShieldCheck className="w-3 h-3" />
                    <span>Gemini API Key đang hoạt động.</span>
                  </p>
                )}
              </div>

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-200">
                  Mô hình Gemini
                </label>
                <select
                  value={geminiModel}
                  onChange={(e) => setGeminiModel(e.target.value)}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  {geminiChatModels.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} ({m.id}){m.desc ? ` - ${m.desc}` : ''}
                    </option>
                  ))}
                </select>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={geminiOtherModel}
                    onChange={(e) => setGeminiOtherModel(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter' && geminiOtherModel.trim()) { e.preventDefault(); setGeminiModel(geminiOtherModel.trim()); setGeminiOtherModel(''); } }}
                    placeholder="Model chưa có trong danh sách? Nhập ID rồi Enter"
                    className="flex-1 bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-[11px] text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                  />
                  <button
                    type="button"
                    disabled={!geminiOtherModel.trim()}
                    onClick={() => { setGeminiModel(geminiOtherModel.trim()); setGeminiOtherModel(''); }}
                    className="px-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-[11px] disabled:opacity-40"
                  >
                    Dùng
                  </button>
                </div>
                <div className="flex items-center justify-between text-[10px] text-slate-500">
                  <span>
                    {geminiCatalog.loading
                      ? 'Đang tải danh sách model…'
                      : geminiCatalog.source === 'live'
                        ? '✓ Danh sách trực tuyến từ Google'
                        : (geminiCatalog.error || 'Danh sách dự phòng (nhập key rồi Lưu để lấy danh sách thật)')}
                  </span>
                  <button type="button" onClick={geminiCatalog.refresh} className="text-indigo-400 hover:underline">
                    Làm mới
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* OpenRouter Tab Settings */}
          {activeTab === 'openrouter' && (
            <div className="space-y-4">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-xs font-semibold text-slate-200 flex items-center space-x-1.5">
                    <Key className="w-3.5 h-3.5 text-emerald-400" />
                    <span>OpenRouter API Key</span>
                  </label>
                  <a
                    href="https://openrouter.ai/keys"
                    target="_blank"
                    rel="noreferrer"
                    className="text-[10px] text-emerald-400 hover:underline flex items-center space-x-0.5"
                  >
                    <span>Lấy key tại OpenRouter.ai</span>
                    <ExternalLink className="w-2.5 h-2.5" />
                  </a>
                </div>

                <input
                  type="password"
                  value={openrouterApiKey}
                  onChange={(e) => setOpenrouterApiKey(e.target.value)}
                  placeholder={
                    settings?.openrouter_api_key_configured
                      ? `Đã cấu hình (${settings.openrouter_api_key_masked})`
                      : 'sk-or-v1-...'
                  }
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                />
                {settings?.openrouter_api_key_configured && !openrouterApiKey && (
                  <p className="text-[10px] text-emerald-400 flex items-center space-x-1">
                    <ShieldCheck className="w-3 h-3" />
                    <span>OpenRouter API Key đang hoạt động.</span>
                  </p>
                )}
              </div>

              {/* Model Preset Selection */}
              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-200">
                  Mô hình OpenRouter
                </label>
                <input
                  type="text"
                  value={orFilter}
                  onChange={(e) => setOrFilter(e.target.value)}
                  placeholder="Lọc theo tên, ví dụ: claude, gpt, deepseek, free…"
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-1.5 text-xs text-slate-200 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                />
                <select
                  value={isCustomModel ? 'custom' : openrouterModel}
                  onChange={(e) => {
                    if (e.target.value === 'custom') {
                      setIsCustomModel(true);
                    } else {
                      setIsCustomModel(false);
                      setOpenrouterModel(e.target.value);
                    }
                  }}
                  className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500"
                >
                  {openrouterPresets.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.name} ({m.id}) - {m.desc}
                    </option>
                  ))}
                  <option value="custom">✏️ Tùy chỉnh (Nhập model ID khác...)</option>
                </select>
                <div className="flex items-center justify-between text-[10px] text-slate-500">
                  <span>
                    {orCatalog.loading
                      ? 'Đang tải danh sách model…'
                      : orCatalog.source === 'live'
                        ? `✓ ${orAll.length} model từ OpenRouter${orQuery ? ` (hiển thị ${openrouterPresets.length})` : ''}`
                        : (orCatalog.error || 'Danh sách dự phòng')}
                  </span>
                  <button type="button" onClick={orCatalog.refresh} className="text-indigo-400 hover:underline">
                    Làm mới
                  </button>
                </div>
              </div>

              {/* Custom Model ID input */}
              {isCustomModel && (
                <div className="space-y-1.5 p-3 rounded-xl bg-slate-950/80 border border-slate-800">
                  <label className="text-[11px] font-medium text-slate-300">
                    Nhập Model ID OpenRouter:
                  </label>
                  <input
                    type="text"
                    value={customModelInput}
                    onChange={(e) => setCustomModelInput(e.target.value)}
                    placeholder="ví dụ: mistralai/mistral-large, cohere/command-r..."
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-3 py-1.5 text-xs text-slate-100 placeholder-slate-600 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                  />
                  <p className="text-[10px] text-slate-500">
                    Xem danh sách hơn 200+ mô hình tại <a href="https://openrouter.ai/models" target="_blank" rel="noreferrer" className="text-indigo-400 underline">openrouter.ai/models</a>
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Embedding Tab Settings */}
          {/* Custom (OpenAI-compatible) providers */}
          {activeTab === 'custom' && (
            <CustomProvidersPanel llmProvider={llmProvider} onSetDefault={(ref) => setLlmProvider(ref)} onChanged={() => onRefreshSettings && onRefreshSettings()} />
          )}

          {activeTab === 'embedding' && (
            <div className="space-y-4">
              <p className="text-[11px] text-slate-400 leading-relaxed">
                Embedding quyết định chất lượng tìm kiếm và trả lời. Vector của các model khác nhau
                không so sánh được, nên khi đổi cách embedding app sẽ index lại dữ liệu ở nền.
              </p>

              {embStatus?.warning && (
                <div className="flex items-start space-x-2 p-3 rounded-xl border border-amber-500/30 bg-amber-500/10 text-[11px] text-amber-200">
                  <AlertTriangle className="w-3.5 h-3.5 mt-0.5 shrink-0" />
                  <span>{embStatus.warning}</span>
                </div>
              )}

              <div className="space-y-1.5">
                <label className="text-xs font-semibold text-slate-200">Cách tạo embedding</label>
                <div className="grid gap-2">
                  {[
                    { id: 'auto', name: 'Tự động', desc: 'Có Gemini key thì dùng Gemini, không thì dùng bản dự phòng (yếu).' },
                    { id: 'gemini', name: 'Google Gemini (API)', desc: 'Chất lượng tốt, nhanh, cần Internet và API key (nhập ở tab Google Gemini).' },
                    { id: 'local', name: 'Local (chạy trên máy)', desc: 'Riêng tư, không cần key. Lần đầu tải model về máy.' },
                    { id: 'hash', name: 'Dự phòng (khớp từ khóa)', desc: 'Không hiểu ngữ nghĩa. Chỉ dùng khi cần chạy offline hoàn toàn.' },
                  ].map((o) => (
                    <button
                      key={o.id}
                      type="button"
                      onClick={() => setEmbProvider(o.id)}
                      className={`text-left p-2.5 rounded-xl border transition-colors ${
                        embProvider === o.id
                          ? 'border-indigo-500/60 bg-indigo-600/10'
                          : 'border-slate-800 bg-slate-950 hover:border-slate-700'
                      }`}
                    >
                      <div className="text-xs font-semibold text-slate-100">{o.name}</div>
                      <div className="text-[10px] text-slate-400">{o.desc}</div>
                    </button>
                  ))}
                </div>
              </div>

              {(embProvider === 'gemini' || embProvider === 'auto') && (
                <div className="space-y-1.5">
                  <label className="text-xs font-semibold text-slate-200">Model embedding Gemini</label>
                  <input
                    type="text"
                    value={embGeminiModel}
                    list="gemini-embedding-models"
                    onChange={(e) => setEmbGeminiModel(e.target.value)}
                    className="w-full bg-slate-950 border border-slate-800 rounded-xl px-3 py-2 text-xs text-slate-200 focus:outline-none focus:ring-1 focus:ring-indigo-500 font-mono"
                  />
                  <datalist id="gemini-embedding-models">
                    <option value="gemini-embedding-001" />
                    <option value="gemini-embedding-2" />
                  </datalist>
                  <p className="text-[10px] text-slate-500">
                    Mặc định <span className="font-mono">gemini-embedding-001</span> (768 chiều, Google cho dùng đến 05/2028).
                    <span className="font-mono"> gemini-embedding-2</span> là bản mới hơn, chưa được kiểm thử trong app này.
                    Model cũ <span className="font-mono">text-embedding-004</span> đã ngừng hoạt động.
                  </p>
                </div>
              )}

              {embProvider === 'local' && (
                <div className="space-y-2">
                  <label className="text-xs font-semibold text-slate-200">Model chạy trên máy</label>
                  {(embStatus?.local_models || []).map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      onClick={() => setEmbLocalModel(m.id)}
                      className={`w-full text-left p-2.5 rounded-xl border transition-colors ${
                        embLocalModel === m.id
                          ? 'border-indigo-500/60 bg-indigo-600/10'
                          : 'border-slate-800 bg-slate-950 hover:border-slate-700'
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="text-xs font-semibold text-slate-100">{m.name}</span>
                        <span className="text-[10px] font-mono text-slate-400">{m.size_gb} GB · {m.dim} chiều</span>
                      </div>
                      <div className="text-[10px] text-slate-400">{m.desc}</div>
                    </button>
                  ))}
                  {embStatus && !embStatus.local_available && (
                    <div className="p-2.5 rounded-xl border border-slate-800 bg-slate-950 text-[10px] text-slate-300">
                      Chưa cài thư viện chạy local. Chạy lệnh rồi khởi động lại app:
                      <div className="mt-1 font-mono text-indigo-300 select-all">
                        pip install -r backend/requirements-local.txt
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Status + actions */}
              <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2.5">
                <div className="flex items-center justify-between text-[11px]">
                  <span className="text-slate-400">Đang áp dụng</span>
                  <span className="font-mono text-slate-200 truncate ml-3">{embStatus?.active_tag || '—'}</span>
                </div>
                {embStatus?.chunks && (
                  <div className="flex items-center justify-between text-[11px]">
                    <span className="text-slate-400">Đoạn đã index / tổng</span>
                    <span className="font-mono text-slate-200">
                      {embStatus.chunks.current} / {embStatus.chunks.total}
                      {embStatus.chunks.stale > 0 && (
                        <span className="text-amber-300"> · {embStatus.chunks.stale} cần index lại</span>
                      )}
                    </span>
                  </div>
                )}

                {embStatus?.reindex?.running && (
                  <div className="space-y-1">
                    <div className="h-1.5 rounded-full bg-slate-800 overflow-hidden">
                      <div
                        className="h-full bg-indigo-500 transition-all"
                        style={{ width: `${embStatus.reindex.total ? (100 * embStatus.reindex.done) / embStatus.reindex.total : 5}%` }}
                      />
                    </div>
                    <div className="text-[10px] text-slate-400">
                      Đang index lại {embStatus.reindex.done}/{embStatus.reindex.total} đoạn
                      {embStatus.resolved_provider === 'local' && !embStatus.local_model_loaded ? ' (lần đầu đang tải model, có thể mất vài phút)…' : '…'}
                    </div>
                  </div>
                )}
                {embStatus?.reindex?.error && !embStatus.reindex.running && (
                  <div className="text-[10px] text-amber-300">Index lại dừng do lỗi: {embStatus.reindex.error}</div>
                )}

                {embTest && (
                  <div className={`text-[11px] ${embTest.ok ? 'text-emerald-400' : 'text-amber-300'}`}>
                    {embTest.ok
                      ? `✓ Hoạt động: ${embTest.dim} chiều, ${embTest.ms} ms`
                      : `✗ ${embTest.error}`}
                  </div>
                )}

                <div className="flex flex-wrap gap-2 pt-1">
                  <button
                    type="button"
                    onClick={runEmbTest}
                    disabled={!!embBusy}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium bg-slate-800 hover:bg-slate-700 text-slate-200 disabled:opacity-50"
                  >
                    {embBusy === 'test' ? 'Đang kiểm tra (lần đầu local có thể lâu)…' : 'Lưu & kiểm tra'}
                  </button>
                  <button
                    type="button"
                    onClick={() => runReindex(false)}
                    disabled={!!embBusy || reindexRunning}
                    className="flex items-center space-x-1 px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-600 hover:bg-indigo-500 text-white disabled:opacity-50"
                  >
                    <RefreshCw className="w-3 h-3" />
                    <span>Index lại phần còn thiếu</span>
                  </button>
                  <button
                    type="button"
                    onClick={() => runReindex(true)}
                    disabled={!!embBusy || reindexRunning}
                    className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 disabled:opacity-50"
                  >
                    Index lại toàn bộ
                  </button>
                </div>
              </div>
            </div>
          )}

          {/* Database Stats */}
          {settings?.stats && (
            <div className="p-3 rounded-xl bg-slate-950 border border-slate-800 space-y-2">
              <div className="flex items-center space-x-1.5 text-xs font-semibold text-slate-300">
                <Database className="w-3.5 h-3.5 text-indigo-400" />
                <span>Dữ liệu Second Brain</span>
              </div>
              <div className="grid grid-cols-3 gap-2 text-center pt-1">
                <div className="p-2 rounded-lg bg-slate-900 border border-slate-800/80">
                  <div className="text-base font-bold text-slate-100 font-mono">
                    {settings.stats.total_notes}
                  </div>
                  <div className="text-[10px] text-slate-400">Ghi chú</div>
                </div>
                <div className="p-2 rounded-lg bg-slate-900 border border-slate-800/80">
                  <div className="text-base font-bold text-slate-100 font-mono">
                    {settings.stats.total_documents}
                  </div>
                  <div className="text-[10px] text-slate-400">Tài liệu</div>
                </div>
                <div className="p-2 rounded-lg bg-slate-900 border border-slate-800/80">
                  <div className="text-base font-bold text-indigo-400 font-mono">
                    {settings.stats.total_chunks}
                  </div>
                  <div className="text-[10px] text-slate-400">Đoạn RAG</div>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 flex justify-end space-x-2 bg-slate-950/40">
          <button
            onClick={onClose}
            className="px-3 py-1.5 rounded-lg text-xs font-medium text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition-colors"
          >
            Đóng
          </button>
          <button
            onClick={handleSave}
            disabled={isSaving}
            className="flex items-center space-x-1.5 px-4 py-1.5 rounded-lg text-xs font-semibold bg-indigo-600 hover:bg-indigo-500 text-white transition-all shadow-md shadow-indigo-600/20"
          >
            {saved ? (
              <>
                <Check className="w-3.5 h-3.5" />
                <span>Đã lưu!</span>
              </>
            ) : (
              <span>{isSaving ? 'Đang lưu...' : 'Lưu cấu hình'}</span>
            )}
          </button>
        </div>
      </div>
    </div>
  );
}
