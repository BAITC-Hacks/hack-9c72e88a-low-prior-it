import { useEffect, useState } from 'react';
import { api, type BacktestRun, type DatasetInfo, type ForecastRequest, type ForecastRun, type ModelInfo, type Turbine } from './api';
import { isActive } from './format';

export default function useDashboard() {
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [datasets, setDatasets] = useState<DatasetInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [issue, setIssue] = useState('2026-01-31T00:00');
  const [horizon, setHorizon] = useState<24 | 48>(48);
  const [source, setSource] = useState<'demo' | 'archive'>('demo');
  const [model, setModel] = useState('demo-power-curve');
  const [run, setRun] = useState<ForecastRun | null>(null);
  const [backtest, setBacktest] = useState<BacktestRun | null>(null);
  const [history, setHistory] = useState<ForecastRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [connected, setConnected] = useState(false);
  const [activeLead, setActiveLead] = useState(1);

  function selectRun(next: ForecastRun) {
    setRun(next); setIssue(new Date(next.request.issued_at).toISOString().slice(0, 16));
    setHorizon(next.request.horizon_hours); setSource(next.request.weather_source);
    setModel(next.request.model_id); setSelected(next.request.turbine_ids); setActiveLead(1);
  }

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.turbines(), api.models(), api.forecasts(), api.backtests(), api.datasets()])
      .then(([t, m, f, b, d]) => {
        if (cancelled) return;
        setTurbines(t); setSelected(t.map(item => item.id)); setModels(m); setHistory(f);
        setDatasets(d); setBacktest(b[0] || null); setConnected(true);
        if (f[0]) selectRun(f[0]);
      }).catch(err => { if (!cancelled) setError(`Cannot connect to the forecasting service. ${err.message}`); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!connected || !run || !isActive(run.status)) return;
    let cancelled = false;
    const id = window.setInterval(() => {
      api.forecast(run.id).then(next => {
        if (cancelled) return;
        setRun(next);
        setHistory(items => [next, ...items.filter(item => item.id !== next.id)].slice(0, 20));
      }).catch(err => { if (!cancelled) { setError(err.message); setConnected(false); window.clearInterval(id); } });
    }, 1000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [run?.id, run?.status, connected]);

  useEffect(() => {
    if (!connected || !backtest || !isActive(backtest.status)) return;
    let cancelled = false;
    const id = window.setInterval(() => {
      api.backtest(backtest.id).then(next => { if (!cancelled) setBacktest(next); })
        .catch(err => { if (!cancelled) { setError(err.message); setConnected(false); window.clearInterval(id); } });
    }, 1500);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [backtest?.id, backtest?.status, connected]);

  async function act(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (err) { setError(err instanceof Error ? err.message : 'Request failed'); }
    finally { setBusy(false); }
  }

  function request(): ForecastRequest {
    if (!issue || !Number.isFinite(new Date(`${issue}Z`).getTime())) throw new Error('Choose a valid forecast issue time.');
    if (!selected.length) throw new Error('Select at least one turbine.');
    return { turbine_ids: selected, issued_at: new Date(`${issue}Z`).toISOString(), horizon_hours: horizon, weather_source: source, model_id: model };
  }

  function submitForecast() {
    return act(async () => { const next = await api.createForecast(request()); setRun(next); setActiveLead(1); setHistory(items => [next, ...items].slice(0, 20)); });
  }

  function refreshForecast() {
    if (!run) return;
    return act(async () => {
      const response = await api.refresh(run.id); setRun(response.run);
      if (response.changed) setHistory(items => [response.run, ...items].slice(0, 20));
      setNotice(response.changed ? 'New inputs detected. Recalculating the forecast.' : 'Inputs are unchanged. This forecast is up to date for its issue time.');
    });
  }

  function startReplay(dataset: string | null) {
    return act(async () => {
      setBacktest(await api.createBacktest({ ...request(), issued_at: '2026-01-31T00:00:00Z', last_issued_at: '2026-02-28T00:00:00Z', evaluation_start: '2026-02-01T00:00:00Z', evaluation_end: '2026-03-01T00:00:00Z', actuals_dataset_id: dataset }));
    });
  }

  function reloadWorkspace() {
    return act(async () => {
      const [t, m, f, b, d] = await Promise.all([api.turbines(), api.models(), api.forecasts(), api.backtests(), api.datasets()]);
      setTurbines(t); setModels(m); setDatasets(d); setHistory(f); setBacktest(b[0] || null); setConnected(true);
      const current = f.find(item => item.id === run?.id);
      if (current) setRun(current);
      else if (!run && f[0]) selectRun(f[0]);
      if (!selected.length) setSelected(t.map(item => item.id));
      setNotice('Workspace data refreshed.');
    });
  }

  const disabled = busy || loading || !connected || isActive(run?.status) || isActive(backtest?.status);
  const dirty = !!run && (new Date(run.request.issued_at).getTime() !== new Date(`${issue}Z`).getTime() || horizon !== run.request.horizon_hours || source !== run.request.weather_source || model !== run.request.model_id || [...selected].sort().join() !== [...run.request.turbine_ids].sort().join());

  return { turbines, models, datasets, selected, issue, horizon, source, model, run, backtest, history, busy, loading, error, notice, connected, activeLead, disabled, dirty,
    setIssue, setHorizon, setSource, setModel, setActiveLead, setError, setNotice, selectRun, submitForecast, refreshForecast, startReplay, reloadWorkspace,
    toggleTurbine: (id: string) => setSelected(ids => ids.includes(id) ? ids.filter(item => item !== id) : [...ids, id]),
  };
}
