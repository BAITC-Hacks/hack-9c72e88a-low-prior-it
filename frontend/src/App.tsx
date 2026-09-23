import { useEffect, useState } from 'react';
import { api, type BacktestRun, type ForecastRequest, type ForecastRun, type ModelInfo, type Turbine } from './api';
import ForecastChart from './ForecastChart';

const active = (status?: string) => status === 'queued' || status === 'running';
const utcTime = (value: string) => new Date(value).toLocaleString('en-GB', { timeZone: 'UTC', dateStyle: 'medium', timeStyle: 'short' });

export default function App() {
  const [turbines, setTurbines] = useState<Turbine[]>([]);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [selected, setSelected] = useState<string[]>([]);
  const [issue, setIssue] = useState('2026-01-31T00:00');
  const [horizon, setHorizon] = useState<24 | 48>(48);
  const [source, setSource] = useState<'demo' | 'archive'>('demo');
  const [model, setModel] = useState('demo-power-curve');
  const [run, setRun] = useState<ForecastRun | null>(null);
  const [backtest, setBacktest] = useState<BacktestRun | null>(null);
  const [history, setHistory] = useState<ForecastRun[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let cancelled = false;
    Promise.all([api.turbines(), api.models(), api.forecasts()]).then(([t, m, f]) => {
      if (cancelled) return;
      setTurbines(t); setSelected(t.map(item => item.id)); setModels(m); setHistory(f);
      setRun(f[0] || null); setConnected(true);
    }).catch(err => { if (!cancelled) setError(`Cannot connect to the API. ${err.message}`); });
    return () => { cancelled = true; };
  }, []);

  useEffect(() => {
    if (!run || !active(run.status)) return;
    let cancelled = false;
    const id = window.setInterval(() => {
      api.forecast(run.id).then(next => { if (!cancelled) setRun(next); })
        .catch(err => { if (!cancelled) { setError(err.message); window.clearInterval(id); } });
    }, 800);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [run?.id, run?.status]);

  useEffect(() => {
    if (!backtest || !active(backtest.status)) return;
    let cancelled = false;
    const id = window.setInterval(() => {
      api.backtest(backtest.id).then(next => { if (!cancelled) setBacktest(next); })
        .catch(err => { if (!cancelled) { setError(err.message); window.clearInterval(id); } });
    }, 1000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, [backtest?.id, backtest?.status]);

  async function act(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (err) { setError(err instanceof Error ? err.message : 'Request failed'); }
    finally { setBusy(false); }
  }

  function request(): ForecastRequest {
    if (!issue) throw new Error('Choose a forecast issue time.');
    if (!selected.length) throw new Error('Select at least one turbine.');
    return { turbine_ids: selected, issued_at: `${issue}:00Z`, horizon_hours: horizon, weather_source: source, model_id: model };
  }

  const points = run?.result?.points || [];
  const average = points.length ? points.reduce((sum, p) => sum + p.power_normalized, 0) / points.length : null;
  const disabled = busy || !connected || active(run?.status);

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <a className="brand" href="/" aria-label="Low Prior home"><span className="brand-icon">↗</span><span>LOW PRIOR<span className="brand-sub">ENERGY INTELLIGENCE</span></span></a>
        <div className="workspace-label">WORKSPACE / 01</div>
        <nav><a className="nav-active" href="#forecast">◉ <span>Wind forecast</span></a><a href="#replay">↻ <span>Historical replay</span></a><a href="#activity">≡ <span>Agent activity</span></a></nav>
        <div className="sidebar-foot"><span className="dot" /> Wind first.<br /><small>Two turbines. One shared forecast workflow.</small></div>
      </aside>

      <main>
        <header><span className="eyebrow">OPERATIONS / WIND</span><span className={`connection ${connected ? 'online' : ''}`}><span className="dot" />{connected ? 'API connected' : 'API disconnected'}</span></header>
        <div className="page-title"><div><h1>See the next 48 hours.</h1><p>Forecast turbine output. Inspect the inputs. Follow every decision.</p></div><span className="version">TEAM STARTER · v0.1</span></div>
        <div className="demo-banner"><strong>Development workspace</strong><span>Demo mode uses synthetic weather and an illustrative model. Real replay requires verified archives and a trained model.</span></div>
        {error && <div className="alert error" role="alert">{error}</div>}
        {notice && <div className="alert" role="status">{notice}</div>}

        <section className="turbine-grid" aria-label="Select turbines">
          {turbines.map((t, index) => <label className={`turbine-card ${selected.includes(t.id) ? 'selected' : ''}`} key={t.id}>
            <div className="turbine-top"><span className="eyebrow">ASSET / 0{index + 1}</span><input type="checkbox" checked={selected.includes(t.id)} onChange={() => setSelected(ids => ids.includes(t.id) ? ids.filter(id => id !== t.id) : [...ids, t.id])} /></div>
            <h2>{t.name}<span className="turbine-symbol" aria-hidden="true">✳</span></h2>
            <p>{t.latitude === null ? 'Coordinates awaiting confirmation' : `${t.latitude?.toFixed(4)}°, ${t.longitude?.toFixed(4)}°`}</p>
            <span className="tag">{t.rated_power_kw == null ? 'Capacity not configured' : `${t.rated_power_kw} kW rated`}</span>
          </label>)}
        </section>

        <section className="panel" id="forecast">
          <div className="section-heading"><div><span className="eyebrow">01 / FORECAST</span><h2>Hourly production outlook</h2></div><span className="tag">Normalized power · %</span></div>
          <form className="controls" onSubmit={event => { event.preventDefault(); void act(async () => { setRun(await api.createForecast(request())); }); }}>
            <label>Issue time · UTC<input aria-label="Issue time UTC" type="datetime-local" step="3600" value={issue} onChange={event => setIssue(event.target.value)} required /></label>
            <label>Horizon<select value={horizon} onChange={event => setHorizon(Number(event.target.value) as 24 | 48)}><option value={24}>24 hours</option><option value={48}>48 hours</option></select></label>
            <label>Weather<select value={source} onChange={event => setSource(event.target.value as 'demo' | 'archive')}><option value="demo">Synthetic demo</option><option value="archive">Verified archive</option></select></label>
            <label>Power model<select value={model} onChange={event => setModel(event.target.value)}>{models.map(m => <option key={m.id} value={m.id}>{m.is_demo ? 'Demo power curve' : `${m.algorithm} · ${m.id.slice(-6)}`}</option>)}</select></label>
            <button className="primary" disabled={disabled || !selected.length} type="submit">{active(run?.status) ? 'Running…' : 'Run forecast ↗'}</button>
          </form>
          {run ? <>
            <div className="stats"><div><span>Run status</span><strong>{run.status}</strong></div><div><span>Mean across selected turbines</span><strong>{average === null ? '—' : `${(average * 100).toFixed(1)}%`}</strong></div><div><span>Hourly predictions</span><strong>{points.length || '—'}</strong></div><div><span>Issue time · UTC</span><strong className="small-value">{utcTime(run.request.issued_at)}</strong></div></div>
            {run.error && <div className="alert error" role="alert">{run.error}</div>}
            {run.result ? <><div className="result-label"><span className={`tag ${run.result.is_demo ? 'amber' : ''}`}>{run.result.is_demo ? 'DEMO RESULT' : 'ARCHIVE RESULT'}</span><span>{run.id}</span></div><ForecastChart run={run} turbines={turbines} />
              <details><summary>Input provenance & limitations</summary><ul>{run.result.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul>{run.result.snapshots.map(snapshot => <p key={snapshot.id}><strong>{snapshot.turbine_id}</strong> · {snapshot.weather_model} · {snapshot.verification}<br />Run: {utcTime(snapshot.run_init)} UTC · Available: {snapshot.available_at ? `${utcTime(snapshot.available_at)} UTC` : 'unverified'}</p>)}</details>
              <div className="actions"><a className="button" href={`/api/v1/forecasts/${run.id}/export`}>Download hourly CSV ↓</a><button disabled={busy} onClick={() => void act(async () => { const response = await api.refresh(run.id); setRun(response.run); setNotice(response.changed ? 'Inputs changed. A new forecast was queued.' : 'Inputs are unchanged. The existing forecast remains current.'); })}>Check for updated inputs ↻</button></div>
              <details><summary>View hourly values</summary><div className="table-scroll"><table><thead><tr><th>UTC time</th><th>Turbine</th><th>Lead</th><th>Normalized power</th></tr></thead><tbody>{points.map(p => <tr key={`${p.turbine_id}-${p.valid_time}`}><td>{utcTime(p.valid_time)}</td><td>{p.turbine_id}</td><td>+{p.lead_hours}h</td><td>{(p.power_normalized * 100).toFixed(2)}%</td></tr>)}</tbody></table></div></details>
            </> : active(run.status) && <div className="empty" role="status">The agent is preparing weather and checking the forecast.</div>}
          </> : <div className="empty"><span>↗</span><h3>Your first forecast starts here.</h3><p>Select your turbines and run the 48-hour demo.</p></div>}
        </section>

        <div className="bottom-grid">
          <section className="panel" id="activity"><div className="section-heading"><div><span className="eyebrow">02 / AGENT</span><h2>Decision log</h2></div><span className="tag">Policy workflow</span></div>
            <ol className="event-list">{run?.events.map((event, i) => <li key={i}><span className={`event-dot ${event.stage === 'failed' ? 'failed' : ''}`} /><div><strong>{event.stage}</strong><p>{event.message}</p><time>{utcTime(event.at)} UTC</time></div></li>)}</ol>{!run?.events.length && <p className="muted">Weather selection, retries and quality checks appear here after a run.</p>}
          </section>
          <section className="panel" id="replay"><div className="section-heading"><div><span className="eyebrow">03 / REPLAY</span><h2>February 2026</h2></div></div><p className="muted">Issue one forecast per day, January 31–February 28 at 00:00 UTC. Score target hours in February. The competition timezone still needs confirmation.</p>
            <button className="primary" disabled={disabled || active(backtest?.status) || !selected.length} onClick={() => void act(async () => {
              setBacktest(await api.createBacktest({ ...request(), issued_at: '2026-01-31T00:00:00Z', last_issued_at: '2026-02-28T00:00:00Z', evaluation_start: '2026-02-01T00:00:00Z', evaluation_end: '2026-03-01T00:00:00Z', actuals_dataset_id: null }));
            })}>{active(backtest?.status) ? 'Replaying…' : 'Run daily replay ↻'}</button>
            {backtest && <div className="replay-result"><strong>{backtest.status}</strong><p>{backtest.forecast_ids.length} daily runs · {backtest.scored_points} scored predictions</p>{backtest.error && <p className="error-text" role="alert">{backtest.error}</p>}{backtest.status === 'succeeded' && <><p className="muted">{backtest.unscored_points} predictions have no actuals attached. Accuracy metrics are unavailable until actual observations are supplied through the API.</p><a href={`/api/v1/backtests/${backtest.id}/export`}>Download February CSV ↓</a></>}</div>}
          </section>
        </div>
        <section className="panel"><div className="section-heading"><h2>Recent runs</h2><button disabled={busy} onClick={() => void act(async () => { const [runs, updatedModels] = await Promise.all([api.forecasts(), api.models()]); setHistory(runs); setModels(updatedModels); })}>Refresh list</button></div>{history.length ? <div className="history">{history.map(item => <button key={item.id} onClick={() => setRun(item)}><strong>{utcTime(item.request.issued_at)} UTC</strong><span>{item.request.weather_source} · {item.request.horizon_hours}h · {item.status}</span></button>)}</div> : <p className="muted">Saved runs will appear here. Refresh after creating a forecast.</p>}</section>
        <footer>LOW PRIOR-IT <span>Wind forecasting workspace · All displayed times are UTC</span></footer>
      </main>
    </div>
  );
}
