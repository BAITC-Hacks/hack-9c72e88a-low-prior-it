import { useId } from 'react';
import type { Turbine } from '../api';
import Icon from './Icon';

export default function StationMap({ turbines, selected, onToggle, disabled }: { turbines: Turbine[]; selected: string[]; onToggle: (id: string) => void; disabled: boolean }) {
  const gridId = useId().replaceAll(':', '');
  const located = turbines.filter(t => t.latitude != null && t.longitude != null);
  const longitude = located.map(t => t.longitude!);
  const latitude = located.map(t => t.latitude!);
  const centreLon = located.length ? (Math.min(...longitude) + Math.max(...longitude)) / 2 : 0;
  const centreLat = located.length ? (Math.min(...latitude) + Math.max(...latitude)) / 2 : 0;
  const lonSpan = located.length ? Math.max(.02, Math.max(...longitude) - Math.min(...longitude)) * 1.6 : 1;
  const latSpan = located.length ? Math.max(.02, Math.max(...latitude) - Math.min(...latitude)) * 1.8 : 1;

  return <section className="panel station-panel" id="stations" aria-labelledby="station-title">
    <div className="panel-heading"><h2 id="station-title"><Icon name="map" />Turbine map</h2><span className="subtle-label">{located.length}/{turbines.length} located</span></div>
    <div className="station-map">
      <svg viewBox="0 0 520 192" role="img" aria-label={located.length ? 'Schematic coordinate map of configured turbines; latitude and longitude axes are independently scaled' : 'Turbine map awaiting confirmed coordinates'}>
        <defs><pattern id={gridId} width="32" height="32" patternUnits="userSpaceOnUse"><path d="M32 0H0v32" fill="none" stroke="var(--border)" strokeWidth=".7" /></pattern></defs>
        <rect width="520" height="192" fill={`url(#${gridId})`} />
        {located.length > 0 && <><text x="14" y="177" className="map-coordinate">{(centreLat - latSpan / 2).toFixed(4)}° lat</text><text x="14" y="20" className="map-coordinate">{(centreLat + latSpan / 2).toFixed(4)}° lat</text>
          {located.map(t => { const x = 260 + (t.longitude! - centreLon) / lonSpan * 420; const y = 96 - (t.latitude! - centreLat) / latSpan * 130; const i = turbines.findIndex(asset => asset.id === t.id); return <g key={t.id}><circle cx={x} cy={y} r="14" className={selected.includes(t.id) ? 'map-marker-ring selected' : 'map-marker-ring'} /><circle cx={x} cy={y} r="4" fill={selected.includes(t.id) ? 'var(--accent)' : 'var(--text-muted)'} /><text x={x + 20} y={y + 4} className="map-station-label">T{String(i + 1).padStart(2, '0')}</text></g>; })}</>}
      </svg>
      <span className="map-north">N<Icon name="arrow" size={13} /></span>
      {!located.length && <div className="map-empty"><div className="map-empty-icon"><Icon name="pin" size={23} /></div><strong>Awaiting station coordinates</strong><span>Verified locations will appear here.</span></div>}
      <span className="map-caption">{located.length ? 'Coordinate schematic · not to scale' : 'Location layer · no stations plotted'}</span>
    </div>
    <div className="station-list">{turbines.map((t, i) => <div className="station-row" key={t.id}><label><input type="checkbox" checked={selected.includes(t.id)} disabled={disabled} onChange={() => onToggle(t.id)} /><Icon name="turbine" size={19} /><span><strong>{t.name}</strong><small>{t.latitude == null ? 'Coordinates unconfirmed' : `${t.latitude.toFixed(4)}°, ${t.longitude?.toFixed(4)}°`}</small></span></label><span className="station-capacity">{t.rated_power_kw == null ? 'Capacity —' : `${t.rated_power_kw.toLocaleString()} kW`}</span>{t.maps_url && <a href={t.maps_url} target="_blank" rel="noreferrer" className="icon-button" title={`Open source location for ${t.name}`} aria-label={`Open source location for ${t.name}`}><Icon name="external" size={13} /></a>}<span className="station-code">T{String(i + 1).padStart(2, '0')}</span></div>)}</div>
    {!turbines.length && <p className="empty-copy">Connect to the API to load the station registry.</p>}
  </section>;
}
