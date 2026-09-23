import { useState } from 'react';
import Papa from 'papaparse';
import { api, type DatasetInfo, type DatasetUpload, type TrainRequest, type Turbine, type WeatherSnapshot } from '../api';
import { utcTime } from '../format';
import Icon from './Icon';

type Props = { datasets: DatasetInfo[]; turbines: Turbine[]; disabled: boolean; onChanged: () => Promise<void> };
const iso = (value: string) => new Date(`${value}Z`).toISOString();

export default function DataWorkspace({ datasets, turbines, disabled, onChanged }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [demo, setDemo] = useState(false);
  const [provenance, setProvenance] = useState('');
  const [dataset, setDataset] = useState('');
  const [algorithm, setAlgorithm] = useState<NonNullable<TrainRequest['algorithm']>>('binned-power-curve');
  const [cutoff, setCutoff] = useState('2026-01-30T23:00');
  const [firstOrigin, setFirstOrigin] = useState('2025-12-01T00:00');
  const [lastOrigin, setLastOrigin] = useState('2026-01-28T00:00');
  const [featureSet, setFeatureSet] = useState<TrainRequest['feature_set']>('scada');
  const [turbineSelection, setTurbine] = useState('');
  const turbine = turbines.some(item => item.id === turbineSelection) ? turbineSelection : turbines[0]?.id || '';
  const [weatherRun, setWeatherRun] = useState('2026-01-31T00:00');
  const [weatherJson, setWeatherJson] = useState('');
  const [snapshots, setSnapshots] = useState<WeatherSnapshot[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const locked = disabled || busy;

  async function act(task: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await task(); } catch (err) { setError(err instanceof Error ? err.message : 'Request failed'); }
    finally { setBusy(false); }
  }

  async function importFile() {
    if (!file) throw new Error('Choose a canonical CSV or dataset JSON file.');
    const text = await file.text();
    let body: DatasetUpload;
    if (file.name.toLowerCase().endsWith('.json')) body = JSON.parse(text);
    else {
      const parsed = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: 'greedy', transformHeader: header => header.trim() });
      if (parsed.errors.length) throw new Error(parsed.errors[0].message);
      const number = (value: string) => {
        if (!value?.trim() || !Number.isFinite(Number(value))) throw new Error('CSV contains an empty or invalid numeric value.');
        return Number(value);
      };
      body = { name: file.name, is_demo: demo, provenance, observations: parsed.data.map(row => ({
        turbine_id: row.turbine_id, valid_time: row.valid_time, available_at: row.available_at,
        wind_speed_ms: number(row.wind_speed_ms), temperature_c: number(row.temperature_c), power_normalized: number(row.power_normalized),
      })) };
    }
    const result = await api.importDataset(body);
    setDataset(result.id);
    await onChanged();
    setNotice(`Imported ${result.rows.toLocaleString()} hourly observations. ${result.is_demo ? 'Dataset is labelled demo.' : ''}`);
  }

  async function train() {
    const body: TrainRequest = {
      dataset_id: dataset, trained_through: iso(cutoff), algorithm,
      feature_set: featureSet, horizon_hours: 48, weather_source: 'archive',
      iterations: 300, depth: 6, learning_rate: 0.05, random_seed: 42,
      loss_function: 'RMSE', l2_leaf_reg: 3, origin_step_hours: 24,
    };
    if (algorithm === 'catboost') Object.assign(body, { first_origin: iso(firstOrigin), last_origin: iso(lastOrigin), horizon_hours: 48, feature_set: featureSet, weather_source: 'archive' });
    const model = await api.train(body);
    await onChanged();
    setNotice(`Model ${model.id} is available in the forecast selector. Training rows: ${model.training_rows.toLocaleString()}.`);
  }

  return <section id="data" className="data-workspace" aria-label="Data, models and weather archive">
    {error && <div className="notice danger" role="alert"><Icon name="warning" /><span>{error}</span></div>}
    {notice && <div className="notice info" role="status"><Icon name="info" /><span>{notice}</span></div>}
    <details className="panel provenance-panel">
      <summary><span><Icon name="grid" />Datasets & model training</span><Icon name="chevron" size={14} /></summary>
      <div className="management-content">
        <p className="muted small">Import hourly observations with explicit timezones and normalized power in [0, 1]. Convert raw turbine readings with the preparation script first.</p>
        <code className="csv-columns">turbine_id,valid_time,available_at,wind_speed_ms,temperature_c,power_normalized</code>
        <form className="management-form" onSubmit={event => { event.preventDefault(); void act(importFile); }}>
          <label className="control-field"><span>Canonical CSV / dataset JSON</span><input type="file" accept=".csv,.json" disabled={locked} onChange={event => setFile(event.target.files?.[0] || null)} required /></label>
          <label className="control-field"><span>Source & transformations (CSV)</span><input value={provenance} disabled={locked} onChange={event => setProvenance(event.target.value)} placeholder="Source, timezone, observation latency" /></label>
          <label className="management-check"><input type="checkbox" checked={demo} disabled={locked} onChange={event => setDemo(event.target.checked)} />Synthetic dataset (CSV)</label>
          <button className="button" disabled={locked || !file}>Import dataset</button>
        </form>
        <form className="management-form training-form" onSubmit={event => { event.preventDefault(); void act(train); }}>
          <label className="control-field"><span>Training dataset</span><select value={dataset} disabled={locked} onChange={event => setDataset(event.target.value)} required><option value="">Select dataset</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}{d.is_demo ? ' · DEMO' : ''}</option>)}</select></label>
          <label className="control-field"><span>Algorithm</span><select value={algorithm} disabled={locked} onChange={event => setAlgorithm(event.target.value as typeof algorithm)}><option value="binned-power-curve">Binned power curve</option><option value="persistence">Persistence baseline</option><option value="weather-ridge">Weather ridge</option><option value="catboost">CatBoost</option></select></label>
          <label className="control-field"><span>Training cutoff · UTC</span><input type="datetime-local" step="3600" value={cutoff} disabled={locked} onChange={event => setCutoff(event.target.value)} required /></label>
          {algorithm === 'catboost' && <>
            <label className="control-field"><span>First training issue · UTC</span><input type="datetime-local" step="3600" value={firstOrigin} disabled={locked} onChange={event => setFirstOrigin(event.target.value)} required /></label>
            <label className="control-field"><span>Last training issue · UTC</span><input type="datetime-local" step="3600" value={lastOrigin} disabled={locked} onChange={event => setLastOrigin(event.target.value)} required /></label>
            <label className="control-field"><span>Features</span><select value={featureSet} disabled={locked} onChange={event => setFeatureSet(event.target.value as typeof featureSet)}><option value="scada">SCADA history</option><option value="scada-extended">SCADA history + weekly lags</option><option value="weather-scada">Verified weather + SCADA</option></select></label>
          </>}
          <button className="button secondary" disabled={locked || !dataset}>{busy ? 'Working…' : 'Train model'}</button>
        </form>
        <p className="muted small">Weather ridge and weather-based CatBoost require verified historical forecasts. CatBoost uses 48-hour targets at daily training issues. All target and availability times must precede the training cutoff.</p>
      </div>
    </details>
    <details className="panel provenance-panel" onToggle={event => {
      if (event.currentTarget.open) api.weather().then(setSnapshots).catch(err => setError(err.message));
    }}>
      <summary><span><Icon name="wind" />Weather archive</span><Icon name="chevron" size={14} /></summary>
      <div className="management-content">
        <form className="management-form" onSubmit={event => { event.preventDefault(); void act(async () => {
          if (!turbine) throw new Error('No configured turbine is available for weather retrieval.');
          const result = await api.fetchWeather({ turbine_id: turbine, run_init: iso(weatherRun), weather_model: 'ecmwf_ifs' });
          setWeatherJson(JSON.stringify(result, null, 2)); setSnapshots(await api.weather());
          setNotice('Candidate downloaded. Historical availability remains unverified.');
        }); }}>
          <label className="control-field"><span>Turbine</span><select value={turbine} disabled={locked} onChange={event => setTurbine(event.target.value)}>{turbines.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label>
          <label className="control-field"><span>ECMWF initialization · UTC</span><input type="datetime-local" step="3600" value={weatherRun} disabled={locked} onChange={event => setWeatherRun(event.target.value)} required /></label>
          <button className="button" disabled={locked || !turbines.length}>Fetch candidate</button>
        </form>
        <p className="muted small">Downloads remain unverified. A verified revision requires a new ID, original publication time, and evidence that the forecast was available then. An estimated delay alone is not evidence.</p>
        <label className="control-field"><span>Inspect saved snapshot</span><select value="" disabled={locked} onChange={event => { const snapshot = snapshots.find(s => s.id === event.target.value); if (snapshot) setWeatherJson(JSON.stringify(snapshot, null, 2)); }}><option value="">{snapshots.length} snapshots · select to inspect</option>{snapshots.map(s => <option key={s.id} value={s.id}>{s.turbine_id} · {utcTime(s.run_init)} UTC · {s.verification} · {s.id}</option>)}</select></label>
        <form className="management-editor" onSubmit={event => { event.preventDefault(); void act(async () => {
          await api.importWeather(JSON.parse(weatherJson)); setSnapshots(await api.weather()); setNotice('New weather snapshot saved.');
        }); }}>
          <label className="control-field"><span>Snapshot JSON</span><textarea rows={9} value={weatherJson} disabled={locked} onChange={event => setWeatherJson(event.target.value)} spellCheck={false} required /></label>
          <button className="button" disabled={locked || !weatherJson.trim()}>Import new revision</button>
        </form>
      </div>
    </details>
  </section>;
}
