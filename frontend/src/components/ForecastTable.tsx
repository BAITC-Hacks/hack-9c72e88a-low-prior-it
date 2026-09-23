import { useMemo, useState } from 'react';
import type { ForecastRun, Turbine } from '../api';
import { seriesColors, utcClock, utcDate } from '../format';
import Icon from './Icon';

export default function ForecastTable({ run, turbines, activeLead, onLeadChange }: { run: ForecastRun | null; turbines: Turbine[]; activeLead: number; onLeadChange: (lead: number) => void }) {
  const [asset, setAsset] = useState('all');
  const [page, setPage] = useState(0);
  const points = useMemo(() => [...(run?.result?.points || [])]
    .filter(p => asset === 'all' || p.turbine_id === asset)
    .sort((a, b) => a.lead_hours - b.lead_hours || a.turbine_id.localeCompare(b.turbine_id)), [run?.result?.points, asset]);
  const pageSize = 8;
  const lastPage = Math.max(0, Math.ceil(points.length / pageSize) - 1);
  const currentPage = Math.min(page, lastPage);
  const visible = points.slice(currentPage * pageSize, (currentPage + 1) * pageSize);
  const snapshots = run?.result?.snapshots || [];

  return <section className="panel table-panel" id="hourly" aria-labelledby="hourly-title">
    <div className="panel-heading"><div className="heading-group"><h2 id="hourly-title"><Icon name="grid" />Hourly forecast</h2><span className="subtle-label">{points.length} predictions · UTC</span></div><div className="panel-actions"><select aria-label="Filter hourly table by turbine" value={asset} onChange={event => { setAsset(event.target.value); setPage(0); }}><option value="all">All turbines</option>{(run?.request.turbine_ids || []).map(id => <option key={id} value={id}>{turbines.find(t => t.id === id)?.name || id}</option>)}</select>{run?.status === 'succeeded' && <a className="button quiet" href={`/api/v1/forecasts/${run.id}/export`}><Icon name="download" />Export CSV</a>}</div></div>
    <div className="table-scroll"><table><caption className="sr-only">Hourly normalized turbine output and corresponding forecast weather. Percentages are capacity fractions, not megawatts.</caption><thead><tr><th scope="col">Time <span>UTC</span></th><th scope="col">Turbine</th><th scope="col">Horizon</th><th scope="col">Power <span>%</span></th><th scope="col">Wind <span>m/s</span></th><th scope="col">Temperature <span>°C</span></th><th scope="col">Weather source</th></tr></thead><tbody>
      {visible.map(p => {
        const snapshot = snapshots.find(s => s.turbine_id === p.turbine_id);
        const weather = snapshot?.points.find(w => new Date(w.valid_time).getTime() === new Date(p.valid_time).getTime());
        const color = seriesColors[(run?.request.turbine_ids.indexOf(p.turbine_id) || 0) % seriesColors.length];
        return <tr key={`${p.turbine_id}-${p.valid_time}`} className={p.lead_hours === activeLead ? 'inspected-row' : ''}>
          <td><button className="table-time" onClick={() => onLeadChange(p.lead_hours)} title="Inspect this forecast hour"><span>{utcDate(p.valid_time)}</span><strong>{utcClock(p.valid_time)}</strong></button></td>
          <td><span className="table-asset"><i style={{ background: color }} />{turbines.find(t => t.id === p.turbine_id)?.name || p.turbine_id}</span></td>
          <td><span className="lead-badge">H+{String(p.lead_hours).padStart(2, '0')}</span></td>
          <td><div className="power-cell"><strong>{(p.power_normalized * 100).toFixed(1)}</strong><span className="power-bar"><i style={{ width: `${p.power_normalized * 100}%`, background: color }} /></span></div></td>
          <td className="numeric">{weather?.wind_speed_ms.toFixed(1) ?? '—'}</td><td className="numeric">{weather?.temperature_c.toFixed(1) ?? '—'}</td>
          <td><span className={`source-label ${snapshot?.verification === 'verified' ? 'verified' : ''}`}><span className="status-dot" />{snapshot?.verification === 'synthetic' ? 'Synthetic' : snapshot?.verification === 'verified' ? 'Verified archive' : 'Unavailable'}</span></td>
        </tr>;
      })}
      {!visible.length && <tr><td colSpan={7} className="table-empty"><Icon name="grid" size={22} /><strong>No hourly predictions yet</strong><span>Run a forecast to inspect power and weather for each turbine.</span></td></tr>}
    </tbody></table></div>
    <div className="panel-foot"><span>{points.length ? `${currentPage * pageSize + 1}–${Math.min((currentPage + 1) * pageSize, points.length)} of ${points.length} predictions` : 'Waiting for forecast data'}</span><div className="pagination"><button className="icon-button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)} aria-label="Previous forecast rows"><Icon name="chevron" className="rotate-180" size={14} /></button><span>{currentPage + 1} / {lastPage + 1}</span><button className="icon-button" disabled={currentPage >= lastPage} onClick={() => setPage(currentPage + 1)} aria-label="Next forecast rows"><Icon name="chevron" size={14} /></button></div></div>
  </section>;
}
