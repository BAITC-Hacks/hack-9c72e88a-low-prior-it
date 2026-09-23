import { useState } from 'react';
import type { ForecastRun, Turbine } from '../api';
import { compassPoint, leadTime, utcTime } from '../format';
import Icon from './Icon';

export default function WeatherPanel({ run, turbines, activeLead }: { run: ForecastRun | null; turbines: Turbine[]; activeLead: number }) {
  const [selection, setSelection] = useState('');
  const snapshots = run?.result?.snapshots || [];
  const snapshot = snapshots.find(s => s.turbine_id === selection) || snapshots[0];
  const moment = run ? leadTime(run.request.issued_at, Math.min(activeLead, run.request.horizon_hours)) : '';
  const weather = snapshot?.points.find(p => new Date(p.valid_time).getTime() === new Date(moment).getTime());
  const validTimes = new Set(run?.result?.points.filter(p => p.turbine_id === snapshot?.turbine_id).map(p => new Date(p.valid_time).getTime()) || []);
  const series = snapshot?.points.filter(p => validTimes.has(new Date(p.valid_time).getTime())) || [];
  const peak = Math.max(1, ...series.map(p => p.wind_speed_ms));

  return <section className="panel weather-panel" aria-labelledby="weather-title">
    <div className="panel-heading"><h2 id="weather-title"><Icon name="wind" />Weather conditions</h2><span className="badge">Forecast</span></div>
    <div className="weather-context"><select aria-label="Weather turbine" value={snapshot?.turbine_id || ''} onChange={e => setSelection(e.target.value)} disabled={!snapshots.length}>
      {!snapshots.length && <option value="">No weather loaded</option>}
      {snapshots.map(s => <option key={s.turbine_id} value={s.turbine_id}>{turbines.find(t => t.id === s.turbine_id)?.name || s.turbine_id}</option>)}
    </select><span className="lead-badge">H+{String(activeLead).padStart(2, '0')}</span></div>
    <div className="wind-reading"><div><span className="field-label">Wind speed</span><div className="weather-value">{weather ? weather.wind_speed_ms.toFixed(1) : '—'}<small>m/s</small></div><span className="muted small">{weather ? `From ${compassPoint(weather.wind_direction_deg)} · ${weather.wind_direction_deg.toFixed(0)}°` : 'Direction unavailable'}</span></div>
      <svg className="wind-compass" viewBox="0 0 110 110" role="img" aria-label={weather ? `Wind from ${weather.wind_direction_deg.toFixed(0)} degrees` : 'Wind direction unavailable'}>
        <circle cx="55" cy="55" r="34" className="compass-ring" /><circle cx="55" cy="55" r="23" className="compass-inner" /><path d="M55 16v8M55 86v8M16 55h8M86 55h8" className="compass-ring" />
        <text x="55" y="10" textAnchor="middle">N</text><text x="104" y="59" textAnchor="middle">E</text><text x="55" y="107" textAnchor="middle">S</text><text x="5" y="59" textAnchor="middle">W</text>
        {weather && <g transform={`rotate(${weather.wind_direction_deg} 55 55)`}><path d="m55 29 8 31-8-5-8 5Z" fill="var(--accent)" /><path d="m55 81 5-24-5 3-5-3Z" fill="var(--text-muted)" opacity=".5" /></g>}
        <circle cx="55" cy="55" r="2" fill="var(--card)" />
      </svg>
    </div>
    <div className="weather-stats"><div><span><Icon name="temperature" />Temperature</span><strong>{weather ? `${weather.temperature_c.toFixed(1)} °C` : '—'}</strong></div><div><span><Icon name="turbine" />Wind height</span><strong>{snapshot ? `${snapshot.wind_height_m} m` : '—'}</strong></div></div>
    <div className="wind-trend"><div className="mini-label"><span>Wind across forecast</span><span>m/s</span></div><svg viewBox="0 0 280 50" role="img" aria-label="Forecast wind speed trend"><path d="M0 43h280M0 22h280" className="chart-gridline" />{series.length > 1 && <polyline points={series.map((p, i) => `${i / (series.length - 1) * 280},${43 - p.wind_speed_ms / peak * 36}`).join(' ')} fill="none" stroke="var(--accent)" strokeWidth="1.7" />}</svg></div>
    <div className="weather-foot"><span>{weather ? `${utcTime(moment)} UTC` : 'Select a forecast to inspect weather'}</span><span><span className={`status-dot ${snapshot?.verification === 'verified' ? 'good' : ''}`} />{snapshot ? snapshot.verification === 'synthetic' ? 'Synthetic' : snapshot.verification : 'Awaiting data'}</span></div>
  </section>;
}
