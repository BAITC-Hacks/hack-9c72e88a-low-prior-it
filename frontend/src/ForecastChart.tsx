import { useEffect, useRef, useState } from 'react';
import { api, type DatasetInfo, type ForecastRun, type Observation, type Turbine } from './api';
import { leadTime, seriesColors, utcClock, utcDate, utcTime } from './format';
import Icon from './components/Icon';

type Props = {
  run: ForecastRun | null;
  turbines: Turbine[];
  datasets: DatasetInfo[];
  horizon: 24 | 48;
  activeLead: number;
  onLeadChange: (lead: number) => void;
};

export default function ForecastChart({ run, turbines, datasets, horizon: requestedHorizon, activeLead, onLeadChange }: Props) {
  const [hidden, setHidden] = useState<string[]>([]);
  const [actualId, setActualId] = useState('');
  const [actuals, setActuals] = useState<Observation[]>([]);
  const [actualError, setActualError] = useState('');
  const [loadingActuals, setLoadingActuals] = useState(false);
  useEffect(() => {
    let cancelled = false;
    setActuals([]); setActualError(''); setLoadingActuals(false);
    if (!actualId || !run?.result?.points.length) return;
    setLoadingActuals(true);
    api.observations(actualId, leadTime(run.request.issued_at, 1), leadTime(run.request.issued_at, run.request.horizon_hours))
      .then(rows => { if (!cancelled) setActuals(rows); })
      .catch(err => { if (!cancelled) setActualError(err.message); })
      .finally(() => { if (!cancelled) setLoadingActuals(false); });
    return () => { cancelled = true; };
  }, [actualId, run?.id, run?.status]);
  const canvasRef = useRef<HTMLDivElement>(null);
  const [width, setWidth] = useState(900);
  useEffect(() => {
    const element = canvasRef.current;
    if (!element) return;
    const observer = new ResizeObserver(entries => setWidth(Math.max(260, entries[0].contentRect.width)));
    observer.observe(element);
    return () => observer.disconnect();
  }, []);
  const points = run?.result?.points || [];
  const horizon = run?.request.horizon_hours || requestedHorizon;
  const ids = run?.request.turbine_ids || [];
  const cursor = Math.min(activeLead, horizon);
  const height = width < 550 ? 250 : 300;
  const baseline = height - 45;
  const right = width - 16;
  const x = (lead: number) => 38 + ((lead - 1) / (horizon - 1)) * (right - 38);
  const y = (power: number) => baseline - power * (baseline - 30);
  const intervals = width < 550 ? (horizon === 48 ? [12, 24, 36, 48] : [6, 12, 18, 24]) : [6, 12, 18, 24, 30, 36, 42, 48];
  const ticks = [1, ...intervals.filter(lead => lead <= horizon)];

  return <div className="forecast-visual">
    <div className="chart-toolbar">
      <div className="chart-legend" aria-label="Visible forecast series">
        {ids.map((id, i) => <button key={id} type="button" className={hidden.includes(id) ? 'legend-item is-muted' : 'legend-item'} aria-pressed={!hidden.includes(id)} onClick={() => setHidden(items => items.includes(id) ? items.filter(item => item !== id) : [...items, id])}>
          <span className="series-mark" style={{ background: seriesColors[i % seriesColors.length] }} />
          {turbines.find(t => t.id === id)?.name || id}
        </button>)}
        {!ids.length && <span className="muted">Turbine output</span>}
      </div>
      <label className="chart-actuals"><span>Actuals</span><select aria-label="Actual observations for chart" value={actualId} onChange={event => setActualId(event.target.value)}><option value="">None</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}{d.is_demo ? ' · DEMO' : ''}</option>)}</select></label>
      <span className="chart-unit">Normalized power <span>%</span></span>
    </div>
    <div className="chart-canvas" ref={canvasRef}>
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${horizon}-hour normalized turbine power forecast. Use the hour slider below to inspect values.`}
        onPointerMove={event => {
          if (!points.length) return;
          const rect = event.currentTarget.getBoundingClientRect();
          const px = ((event.clientX - rect.left) / rect.width) * width;
          onLeadChange(Math.max(1, Math.min(horizon, Math.round(1 + ((px - 38) / (right - 38)) * (horizon - 1)))));
        }}>
        {[0, .2, .4, .6, .8, 1].map(value => <g key={value}>
          <line x1="38" x2={right} y1={y(value)} y2={y(value)} className="chart-gridline" />
          <text x="25" y={y(value) + 4} textAnchor="end" className="chart-axis">{Math.round(value * 100)}</text>
        </g>)}
        {ticks.map(lead => <g key={lead}>
          <line x1={x(lead)} x2={x(lead)} y1="30" y2={baseline} className="chart-gridline vertical" />
          <text x={x(lead)} y={baseline + 22} textAnchor={lead === horizon ? 'end' : 'middle'} className="chart-axis">{run ? utcClock(leadTime(run.request.issued_at, lead)) : `+${lead}h`}</text>
          {run && (lead === 1 || lead === 24 || lead === 48) && <text x={x(lead)} y={baseline + 39} textAnchor={lead === horizon ? 'end' : 'middle'} className="chart-axis secondary">{utcDate(leadTime(run.request.issued_at, lead))}</text>}
        </g>)}
        {horizon === 48 && <g><line x1={x(24)} x2={x(24)} y1="22" y2={baseline} className="day-divider" /><text x={x(24) + 10} y="15" className="chart-axis secondary">DAY 2</text></g>}
        {ids.map((id, i) => {
          if (hidden.includes(id)) return null;
          const series = points.filter(p => p.turbine_id === id);
          if (!series.length) return null;
          const path = series.map(p => `${x(p.lead_hours)},${y(p.power_normalized)}`).join(' ');
          const color = seriesColors[i % seriesColors.length];
          return <g key={id}>
            {i === 0 && <polygon points={`${x(series[0].lead_hours)},${baseline} ${path} ${x(series[series.length - 1].lead_hours)},${baseline}`} fill={color} fillOpacity=".045" />}
            <polyline fill="none" stroke={color} strokeWidth="2.4" strokeLinejoin="round" strokeLinecap="round" points={path} />
            {actuals.filter(row => row.turbine_id === id).map(row => {
              const lead = (new Date(row.valid_time).getTime() - new Date(run!.request.issued_at).getTime()) / 3600000;
              return <circle key={row.valid_time} cx={x(lead)} cy={y(row.power_normalized)} r="3" fill="var(--card)" stroke={color} strokeWidth="1.5"><title>{turbines.find(t => t.id === id)?.name || id} actual: {(row.power_normalized * 100).toFixed(1)}%</title></circle>;
            })}
          </g>;
        })}
        {points.length > 0 && <g>
          <line x1={x(cursor)} x2={x(cursor)} y1="24" y2={baseline} className="chart-cursor" />
          {ids.map((id, i) => {
            const point = points.find(p => p.turbine_id === id && p.lead_hours === cursor);
            return point && !hidden.includes(id) ? <circle key={id} cx={x(cursor)} cy={y(point.power_normalized)} r="4" fill={seriesColors[i % seriesColors.length]} stroke="var(--card)" strokeWidth="2" /> : null;
          })}
        </g>}
      </svg>
      {!points.length && <div className="chart-empty"><Icon name="chart" size={25} /><strong>{run?.status === 'failed' ? 'Forecast unavailable' : run && ['queued', 'running'].includes(run.status) ? 'Preparing hourly forecast' : 'Ready for your first forecast'}</strong><span>{run?.status === 'failed' ? 'Review the agent log and update the inputs.' : 'Choose an issue time and run a 24- or 48-hour forecast.'}</span></div>}
    </div>
    {actualId && <p className="actuals-status" role={actualError ? 'alert' : 'status'}>{actualError || (loadingActuals ? 'Loading actual observations…' : `${actuals.filter(row => ids.includes(row.turbine_id)).length} observations in this window · hollow circles show actual output`)}</p>}
    <div className="chart-inspector">
      <div className="inspection-time"><Icon name="clock" /><span>{run && points.length ? utcTime(leadTime(run.request.issued_at, cursor)) : 'Forecast hour'} <small>UTC</small></span><span className="lead-badge">H+{String(cursor).padStart(2, '0')}</span></div>
      <div className="inspection-values">{ids.map((id, i) => {
        const point = points.find(p => p.turbine_id === id && p.lead_hours === cursor);
        return <span key={id}><i style={{ background: seriesColors[i % seriesColors.length] }} />{turbines.find(t => t.id === id)?.name || id}<strong>{point ? `${(point.power_normalized * 100).toFixed(1)}%` : '—'}</strong></span>;
      })}</div>
    </div>
    <input className="forecast-scrubber" type="range" aria-label="Inspect forecast hour" aria-valuetext={run ? `${utcTime(leadTime(run.request.issued_at, cursor))} UTC, ${cursor} hours ahead` : `${cursor} hours ahead`} min={1} max={horizon} value={cursor} disabled={!points.length} onChange={event => onLeadChange(Number(event.target.value))} />
  </div>;
}
