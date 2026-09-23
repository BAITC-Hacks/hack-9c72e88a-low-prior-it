import type { ForecastRun, Turbine } from './api';

const colors = ['#23735a', '#c58135'];

export default function ForecastChart({ run, turbines }: { run: ForecastRun; turbines: Turbine[] }) {
  const points = run.result?.points || [];
  const horizon = run.request.horizon_hours;
  const x = (lead: number) => 56 + ((lead - 1) / (horizon - 1)) * 700;
  const y = (power: number) => 234 - power * 200;
  return (
    <div className="chart-wrap">
      <svg viewBox="0 0 800 282" role="img" aria-label={`Hourly normalized power forecast for the next ${horizon} hours`}>
        {[0, 0.25, 0.5, 0.75, 1].map(value => (
          <g key={value}>
            <line x1="56" x2="756" y1={y(value)} y2={y(value)} stroke="#e4e9e4" />
            <text x="42" y={y(value) + 4} textAnchor="end">{value * 100}%</text>
          </g>
        ))}
        {[1, ...[12, 24, 36, 48].filter(lead => lead <= horizon)].map(lead => (
          <text key={lead} x={x(lead)} y="263" textAnchor="middle">+{lead}h</text>
        ))}
        {run.request.turbine_ids.map((id, index) => (
          <polyline key={id} fill="none" stroke={colors[index % colors.length]} strokeWidth="3"
            strokeLinejoin="round" strokeLinecap="round"
            points={points.filter(p => p.turbine_id === id).map(p => `${x(p.lead_hours)},${y(p.power_normalized)}`).join(' ')} />
        ))}
      </svg>
      <div className="legend">{run.request.turbine_ids.map((id, index) => (
        <span key={id}><i style={{ background: colors[index % colors.length] }} />{turbines.find(t => t.id === id)?.name || id}</span>
      ))}</div>
    </div>
  );
}
