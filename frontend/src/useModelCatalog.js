import { useCallback, useEffect, useState } from 'react';
import { api } from './api';

/**
 * Loads the live chat-model list for a provider ('gemini' | 'openrouter').
 * source === 'live' means it came from the provider, 'fallback' means a built-in list.
 */
export function useModelCatalog(provider, enabled = true) {
  const [state, setState] = useState({ models: null, source: null, error: null, loading: false });

  const load = useCallback(async (refresh = false) => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const data = await api.models(provider, refresh);
      setState({ models: data.models || [], source: data.source, error: data.error || null, loading: false });
    } catch (err) {
      setState({ models: null, source: 'fallback', error: err.message, loading: false });
    }
  }, [provider]);

  useEffect(() => {
    if (enabled) load(false);
  }, [enabled, load]);

  return { ...state, refresh: () => load(true) };
}
