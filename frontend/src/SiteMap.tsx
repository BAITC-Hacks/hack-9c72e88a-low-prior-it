import type { Schema } from './api';

export default function SiteMap({ turbines }: { turbines: Schema<'Turbine'>[] }) {
  const located = turbines.filter(t => t.latitude != null && t.longitude != null);
  if (!located.length) return <p className="muted">Координаты площадки не заданы.</p>;
  const lat = located.reduce((s, t) => s + t.latitude!, 0) / located.length;
  const lon = located.reduce((s, t) => s + t.longitude!, 0) / located.length;
  const meters = located.map(t => ({ ...t, east: (t.longitude! - lon) * 111320 * Math.cos(lat * Math.PI / 180), north: (t.latitude! - lat) * 111320 }));
  const extent = Math.max(250, ...meters.map(t => Math.max(Math.abs(t.east), Math.abs(t.north)) + 100));
  const scale = 120 / extent;
  return <figure className="site-map"><svg viewBox="0 0 680 310" role="img" aria-label="Карта-схема расположения турбин по подтверждённым координатам; север сверху">
    <defs><pattern id="site-grid" width="34" height="31" patternUnits="userSpaceOnUse"><path d="M 34 0 L 0 0 0 31" fill="none" stroke="#dce6d9" strokeWidth="1"/></pattern></defs>
    <rect width="680" height="310" rx="10" fill="#f0f5eb"/><rect width="680" height="310" fill="url(#site-grid)"/>
    <text x="25" y="30" fill="#708569" fontSize="11">ШЕЛЕКСКИЙ КОРИДОР</text>
    <path d="M635 60 V28 M630 35 L635 25 L640 35" fill="none" stroke="#64855e" strokeWidth="2"/><text x="630" y="78" fill="#64855e" fontSize="12">N</text>
    {meters.map((t, i) => { const x = 340 + t.east * scale, y = 150 - t.north * scale; return <g key={t.id}>
      <circle cx={x} cy={y} r="24" fill={i ? '#f2dcbe' : '#cee4ba'}/><circle cx={x} cy={y} r="7" fill={i ? '#c68d49' : '#347e53'}/>
      <text x={x + 32} y={y - 3} fill="#3c6641" fontSize="13" fontWeight="600">{t.name}</text><text x={x + 32} y={y + 15} fill="#7b9171" fontSize="10">{t.latitude!.toFixed(6)}, {t.longitude!.toFixed(6)}</text>
    </g>; })}
    <path d={`M25 269 V276 H${25 + 100 * scale} V269`} fill="none" stroke="#66805e" strokeWidth="2"/><text x="25" y="293" fill="#71816b" fontSize="10">100 м · приближённая локальная проекция</text>
  </svg><figcaption>Схема по координатам, без топографической подложки. Север сверху.</figcaption></figure>;
}
