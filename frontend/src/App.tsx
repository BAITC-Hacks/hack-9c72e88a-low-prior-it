import { Component, lazy, Suspense, useEffect, useState, type ReactNode } from 'react';
import ForecastChart from './ForecastChart';
import AgentPanel from './components/AgentPanel';
import DataWorkspace from './components/DataWorkspace';
import ForecastTable from './components/ForecastTable';
import Icon, { type IconName } from './components/Icon';
import ProfileMenu from './components/ProfileMenu';
import ReplayPanel from './components/ReplayPanel';
import StationMap from './components/StationMap';
import WeatherPanel from './components/WeatherPanel';
import { isActive, utcTime } from './format';
import { initialSection, sectionFromHash, workspaceForSection, type WorkspaceSection } from './navigation';
import useDashboard from './useDashboard';

const ExploreView = lazy(() => import('./explore/ExploreView'));
class ExploreBoundary extends Component<{ children: ReactNode; onForecast: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    return this.state.failed ? <section className="dashboard"><div className="panel"><h2>Energy explorer could not load</h2><p className="muted">Reload this page to try again, or continue to the forecast workspace.</p><div className="panel-actions"><button className="button" onClick={() => window.location.reload()}>Reload page</button><button className="button primary" onClick={this.props.onForecast}>Open forecast</button></div></div></section> : this.props.children;
  }
}
function readInitialSection(): WorkspaceSection {
  let savedView: string | null = null;
  try { savedView = localStorage.getItem('low-prior-view'); } catch { /* Use the URL when storage is unavailable. */ }
  return initialSection(window.location.hash, savedView);
}

const navigation: { id: WorkspaceSection; title: string; icon: IconName }[] = [
  { id: 'explore', title: 'Explore', icon: 'globe' },
  { id: 'forecast', title: 'Forecast', icon: 'chart' },
  { id: 'stations', title: 'Assets', icon: 'map' },
  { id: 'activity', title: 'Agent', icon: 'activity' },
  { id: 'replay', title: 'Backtesting', icon: 'bars' },
  { id: 'data', title: 'Data & models', icon: 'grid' },
];

export default function App() {
  const d = useDashboard();
  const [section, setSection] = useState(readInitialSection);
  const view = workspaceForSection(section);
  const [exploreVisited, setExploreVisited] = useState(() => section === 'explore');
  const [navigationRevision, setNavigationRevision] = useState(0);
  const [assetRevision, setAssetRevision] = useState(0);
  function navigate(id: WorkspaceSection) {
    const next = workspaceForSection(id);
    setSection(id); setNavigationRevision(value => value + 1);
    if (next === 'explore') setExploreVisited(true);
    try { localStorage.setItem('low-prior-view', next); } catch { /* Session-only when storage is unavailable. */ }
    if (window.location.hash !== `#${id}`) window.location.hash = id;
  }
  useEffect(() => {
    // Give the initial history entry a route before the first navigation so Back
    // returns to the original workspace instead of an ignored empty hash.
    if (window.location.hash !== `#${section}`) window.history.replaceState(window.history.state, '', `#${section}`);
    const update = () => {
      const id = sectionFromHash(window.location.hash) || 'explore';
      if (window.location.hash !== `#${id}`) window.history.replaceState(window.history.state, '', `#${id}`);
      navigate(id);
    };
    window.addEventListener('hashchange', update);
    return () => window.removeEventListener('hashchange', update);
  }, []);
  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const target = document.getElementById(section === 'forecast' ? 'forecast-workspace' : section);
      if (view === 'forecast' && section !== 'forecast') target?.scrollIntoView();
      else window.scrollTo({ top: 0 });
      if (target && navigationRevision > 0) {
        target.setAttribute('tabindex', '-1');
        target.focus({ preventScroll: true });
      }
    });
    return () => window.cancelAnimationFrame(frame);
  }, [view, section, navigationRevision]);
  function refreshWorkspace() {
    setAssetRevision(value => value + 1);
    return d.reloadWorkspace();
  }
  function openForecast(ids: string[]) {
    d.chooseTurbines(ids);
    navigate('forecast');
  }
  const points = d.run?.result?.points || [];
  const pointKeys = new Set(points.map(p => `${p.turbine_id}:${new Date(p.valid_time).getTime()}`));
  const wind = (d.run?.result?.snapshots || []).flatMap(s => s.points.filter(p => pointKeys.has(`${s.turbine_id}:${new Date(p.valid_time).getTime()}`)));
  const mean = points.length ? points.reduce((sum, p) => sum + p.power_normalized, 0) / points.length : null;
  const peak = points.length ? Math.max(...points.map(p => p.power_normalized)) : null;
  const meanWind = wind.length ? wind.reduce((sum, p) => sum + p.wind_speed_ms, 0) / wind.length : null;
  const covered = new Set(points.map(p => p.turbine_id)).size;
  const forecastHorizon = d.run?.request.horizon_hours || d.horizon;
  const forecastModel = d.models.find(m => m.id === d.run?.request.model_id);
  const history = d.run && !d.history.some(r => r.id === d.run?.id) ? [d.run, ...d.history] : d.history;

  return <div className="app-shell">
    <a className="skip-link" href="#main" onClick={event => { event.preventDefault(); document.getElementById('main')?.focus(); }}>Skip to dashboard</a>
    <aside className="navigation-rail" aria-label="Workspace navigation">
      <a className="rail-brand" href="#explore" onClick={event => { event.preventDefault(); navigate('explore'); }} aria-label="Low Prior energy explorer"><Icon name="globe" size={28} /></a>
      <nav>{navigation.map(item => <a key={item.id} href={`#${item.id}`} className={section === item.id ? 'rail-link selected' : 'rail-link'} title={item.title} aria-label={item.title} aria-current={section === item.id ? 'location' : undefined} onClick={event => { event.preventDefault(); navigate(item.id); }}><Icon name={item.icon} size={20} /><span className="rail-label">{item.title}</span></a>)}</nav>
      <div className="rail-bottom"><span>v0.1</span></div>
    </aside>

    <div className="workspace">
      <header className="topbar"><div className="topbar-title"><span className="wordmark">LOW PRIOR<span className="wordmark-divider" /></span><div><h1>Energy operations</h1><span className="topbar-subtitle">Generation forecasting & monitoring</span></div></div><div className="topbar-tools"><span className="timezone"><Icon name="clock" size={13} />UTC</span><span className={`connection ${d.connected ? 'connected' : d.loading ? '' : 'disconnected'}`}><span className="status-dot" />{d.loading ? 'Connecting' : d.connected ? 'Connected' : 'Disconnected'}</span><button className="icon-button" onClick={() => void refreshWorkspace()} disabled={d.busy || d.loading} aria-label="Refresh workspace data" title="Refresh workspace data"><Icon name="refresh" className={d.busy ? 'spinning' : ''} /></button><ProfileMenu /></div></header>

      <main id="main" tabIndex={-1}>
        {(d.error || d.notice) && <div className="workspace-notices">
          {d.error && <div className="notice danger" role="alert"><Icon name="warning" /><span>{d.error}</span><button className="icon-button" onClick={() => d.setError('')} aria-label="Dismiss error"><Icon name="close" size={14} /></button></div>}
          {d.notice && <div className="notice info" role="status"><Icon name="info" /><span>{d.notice}</span><button className="icon-button" onClick={() => d.setNotice('')} aria-label="Dismiss notification"><Icon name="close" size={14} /></button></div>}
        </div>}
        {exploreVisited && <div id="explore" tabIndex={-1} aria-label="Energy explorer workspace" hidden={view !== 'explore'}><ExploreBoundary onForecast={() => navigate('forecast')}><Suspense fallback={<div className="workspace-loading" role="status">Loading energy explorer…</div>}><ExploreView active={view === 'explore'} refreshRevision={assetRevision} forecastingDisabled={d.disabled} onOpenForecast={openForecast} /></Suspense></ExploreBoundary></div>}
        <div id="forecast-workspace" className="dashboard" aria-label="Forecast workspace" hidden={view !== 'forecast'}>
        <div className="workspace-heading"><div className="section-context"><span className="context-mark" /><h2>Forecast workspace</h2><span className="badge">Wind energy</span></div><label className="history-control"><Icon name="clock" size={13} /><span className="sr-only">Saved forecast</span><select aria-label="Saved forecast" value={d.run?.id || ''} disabled={!history.length || d.busy || isActive(d.run?.status)} onChange={event => { const next = history.find(r => r.id === event.target.value); if (next) d.selectRun(next); }}>
          {!history.length && <option value="">No saved forecasts</option>}{history.map(run => <option key={run.id} value={run.id}>{utcTime(run.request.issued_at)} UTC · {run.request.horizon_hours}h · {run.status} · {run.id.slice(-5)}</option>)}
        </select></label></div>

        <section className="panel forecast-controls" aria-label="Forecast configuration">
          <form onSubmit={event => { event.preventDefault(); void d.submitForecast(); }}>
            <label className="control-field issue-field"><span><Icon name="calendar" size={13} />Issue time <small>UTC</small></span><input type="datetime-local" aria-label="Forecast issue time UTC" step="3600" value={d.issue} onChange={event => d.setIssue(event.target.value)} required disabled={d.disabled} /></label>
            <fieldset className="horizon-control"><legend>Forecast horizon</legend><div className="segmented" aria-label="Forecast horizon">{([24, 48] as const).map(hours => <button key={hours} type="button" aria-pressed={d.horizon === hours} className={d.horizon === hours ? 'active' : ''} disabled={d.disabled} onClick={() => d.setHorizon(hours)}>{hours}h</button>)}</div></fieldset>
            <label className="control-field"><span>Weather source</span><select value={d.source} onChange={event => d.setSource(event.target.value as 'demo' | 'archive')} disabled={d.disabled}><option value="demo">Synthetic demo</option><option value="archive">Verified archive</option></select></label>
            <label className="control-field model-field"><span>Prediction model</span><select value={d.model} onChange={event => d.setModel(event.target.value)} disabled={d.disabled}>{!d.models.length && <option value="demo-power-curve">Demo power curve</option>}{d.models.map(model => <option key={model.id} value={model.id}>{model.id === 'demo-power-curve' ? 'Demo power curve' : `${model.is_demo ? 'Demo · ' : ''}${model.algorithm} · ${model.id.slice(-6)}`}</option>)}</select></label>
            <button className="button primary run-button" type="submit" disabled={d.disabled || !d.selected.length}><Icon name={isActive(d.run?.status) ? 'refresh' : 'play'} size={14} className={isActive(d.run?.status) ? 'spinning' : ''} />{isActive(d.run?.status) ? 'Forecasting…' : 'Run forecast'}</button>
          </form>
          <div className="asset-controls"><span className="field-label">Forecast assets</span><div className="asset-chips">{d.turbines.map(t => <button key={t.id} type="button" className={`asset-chip ${d.selected.includes(t.id) ? 'selected' : ''}`} aria-pressed={d.selected.includes(t.id)} disabled={d.disabled} onClick={() => d.toggleTurbine(t.id)}><Icon name="turbine" size={14} />{t.name}<Icon name={d.selected.includes(t.id) ? 'check' : 'close'} size={12} /></button>)}{!d.turbines.length && <span className="muted small">{d.loading ? 'Loading turbines…' : 'Station registry unavailable'}</span>}</div><span className="asset-count">{d.selected.length} selected</span></div>
        </section>

        <section className="kpi-grid" aria-label="Forecast key indicators">
          <article className="kpi-card"><div><span>Mean normalized output</span><Icon name="chart" /></div><strong>{mean == null ? '—' : (mean * 100).toFixed(1)}<small>%</small></strong><p>Across forecast turbines & hours</p></article>
          <article className="kpi-card"><div><span>Peak turbine output</span><Icon name="bars" /></div><strong>{peak == null ? '—' : (peak * 100).toFixed(1)}<small>%</small></strong><p>Highest individual hourly prediction</p></article>
          <article className="kpi-card"><div><span>Mean forecast wind</span><Icon name="wind" /></div><strong>{meanWind == null ? '—' : meanWind.toFixed(1)}<small>m/s</small></strong><p>Weather inputs over the forecast</p></article>
          <article className="kpi-card"><div><span>Forecast coverage</span><Icon name="turbine" /></div><strong>{points.length ? covered : '—'}<small>/ {d.run?.request.turbine_ids.length ?? d.selected.length} turbines</small></strong><p>{points.length ? `${points.length} hourly predictions · ${forecastHorizon}h horizon` : 'Waiting for a completed run'}</p></article>
        </section>

        <div className="forecast-grid">
          <section className="panel power-panel" id="forecast" aria-labelledby="forecast-title">
            <div className="panel-heading"><div><h2 id="forecast-title"><span className="context-mark" />{forecastHorizon}-hour power forecast</h2><p className="panel-subtitle">{d.run ? `Issued ${utcTime(d.run.request.issued_at)} UTC · Hourly resolution` : 'Hourly normalized generation for selected turbines'}</p></div><div className="panel-actions"><span className={`badge ${d.run?.status === 'failed' ? 'danger' : d.run?.status === 'succeeded' ? 'accent' : ''}`}><span className="status-dot" />{d.run?.status === 'succeeded' ? 'Complete' : d.run?.status || 'Awaiting run'}</span>{d.run?.status === 'succeeded' && <button className="icon-button" title="Check for updated forecast inputs" aria-label="Check for updated forecast inputs" disabled={d.disabled} onClick={() => void d.refreshForecast()}><Icon name="refresh" size={14} /></button>}</div></div>
            {d.dirty && <div className="pending-inputs"><Icon name="info" size={13} />Controls changed. Run a new forecast to update the chart.</div>}
            {d.run?.error && <div className="notice danger" role="alert"><Icon name="warning" /><span>{d.run.error}</span></div>}
            <ForecastChart key={d.run?.id || 'empty'} run={d.run} turbines={d.turbines} datasets={d.datasets} horizon={d.horizon} activeLead={d.activeLead} onLeadChange={d.setActiveLead} />
          </section>
          <WeatherPanel run={d.run} turbines={d.turbines} activeLead={d.activeLead} />
        </div>

        <div className="context-grid"><StationMap turbines={d.turbines} selected={d.selected} onToggle={d.toggleTurbine} disabled={d.disabled} /><AgentPanel run={d.run} /></div>

        <ForecastTable key={d.run?.id || 'empty-table'} run={d.run} turbines={d.turbines} activeLead={d.activeLead} onLeadChange={d.setActiveLead} />

        <ReplayPanel backtest={d.backtest} datasets={d.datasets} models={d.models} turbines={d.turbines} disabled={d.disabled || !d.selected.length} onReplay={dataset => void d.startReplay(dataset)} />

        <DataWorkspace datasets={d.datasets} turbines={d.turbines} disabled={d.disabled} onChanged={refreshWorkspace} />

        <details className="panel provenance-panel"><summary><span><Icon name="shield" />Forecast provenance & model details</span><Icon name="chevron" size={14} /></summary><div className="provenance-content"><div className="provenance-model"><span className="field-label">Prediction model</span><strong>{forecastModel?.algorithm || 'No model result'}</strong><span>Training cutoff: {forecastModel?.trained_through ? `${utcTime(forecastModel.trained_through)} UTC` : 'Not applicable / untrained demo'}</span><span>Uncertainty: not calibrated</span>{d.run && <code>{d.run.id}</code>}</div><div className="provenance-weather">{d.run?.result?.snapshots.map(snapshot => <div key={snapshot.id}><strong>{d.turbines.find(t => t.id === snapshot.turbine_id)?.name || snapshot.turbine_id}</strong><span>{snapshot.weather_model} · {snapshot.verification}</span><span>Initialized {utcTime(snapshot.run_init)} UTC</span><span>Available {snapshot.available_at ? `${utcTime(snapshot.available_at)} UTC` : 'unverified'}</span></div>)}</div>{d.run?.result?.warnings.length ? <ul>{d.run.result.warnings.map(warning => <li key={warning}>{warning}</li>)}</ul> : <p className="muted">Model and weather lineage appear with the forecast result.</p>}</div></details>
        <footer className="workspace-footer"><span><Icon name="globe" size={13} />LOW PRIOR-IT <span className="footer-divider">/</span> Energy intelligence</span><span>Wind forecasting · UTC time · Normalized power</span></footer>
        </div>
      </main>
    </div>
  </div>;
}
