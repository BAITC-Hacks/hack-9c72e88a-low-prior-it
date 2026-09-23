import { useMemo } from 'react';
import type { ForecastRun } from '../api';
import { utcClock, utcDate, utcTime } from '../format';
import { deriveForecastSignals, forecastBrief, type OutputWindow } from '../insights';
import Icon from './Icon';
import '../insights.css';

const windowLabel = (window: OutputWindow) => `${utcDate(window.start)} ${utcClock(window.start)} – ${utcDate(window.end) === utcDate(window.start) ? '' : `${utcDate(window.end)} `}${utcClock(window.end)} UTC`;

export default function ForecastInsights({ run, activeLead, onInspect }: {
  run: ForecastRun | null;
  activeLead: number;
  onInspect: (lead: number) => void;
}) {
  const signals = useMemo(() => deriveForecastSignals(run), [run]);
  const complete = run?.status === 'succeeded' && !!run.result;
  const demo = run?.result?.is_demo;
  const hourByLead = new Map(signals.hours.map(hour => [hour.lead, hour]));
  const ramp = signals.ramp;
  function downloadBrief() {
    if (!run || !complete) return;
    const url = URL.createObjectURL(new Blob([forecastBrief(run, signals)], { type: 'text/markdown;charset=utf-8' }));
    const link = document.createElement('a');
    link.href = url; link.download = `low-prior-${run.id}-brief.md`; link.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="operations-panel" aria-labelledby="operations-title" id="insights">
    <div className="operations-intro">
      <div><span className="section-label"><Icon name="activity" size={13} /> FORECAST → DECISION</span><h2 id="operations-title">See what the next hours hold.</h2><p>Generation windows and changes to review, directly from this forecast.</p></div>
      <div className="operations-actions"><span className={`badge ${demo ? 'warning' : ''}`}>{complete ? demo ? 'Demo / provisional signals' : 'Planning signals' : 'Awaiting forecast'}</span><button className="button" onClick={downloadBrief} disabled={!complete}><Icon name="download" size={14} />Export brief</button></div>
    </div>
    {!complete ? <div className="operations-empty"><span className="operations-empty-icon"><Icon name="activity" size={28} /></span><div><strong>Your forecast, translated into useful signals.</strong><p>Run a forecast to reveal three-hour output windows, the largest hourly change, and a portable brief with the model and weather sources.</p></div></div> : <>
      <div className="operations-signal-row">
        {([{ id: 'high', title: 'Highest output window', icon: 'sun', value: signals.high, hint: 'Review the strongest three-hour generation window.' }, { id: 'low', title: 'Lowest output window', icon: 'clock', value: signals.low, hint: 'Plan around lower output; assess site conditions separately.' }] as const).map(item => <button type="button" key={item.id} className={`signal-card signal-${item.id}`} disabled={!item.value} onClick={() => item.value && onInspect(item.value.firstLead)} aria-label={item.value ? `Inspect ${item.title.toLowerCase()}, ${(item.value.mean * 100).toFixed(1)} percent mean normalized output, ${windowLabel(item.value)}` : `${item.title}: insufficient coverage`}>
          <span className="signal-label"><Icon name={item.icon} size={16} />{item.title}<Icon name="arrow" size={15} /></span>
          <span className="signal-number">{item.value ? (item.value.mean * 100).toFixed(1) : '—'}<small>% <span>mean output</span></small></span>
          <span className="signal-time">{item.value ? windowLabel(item.value) : 'Three complete consecutive hours needed'}</span>
          <span className="signal-hint">{item.hint}</span>
        </button>)}
        <button type="button" className="signal-card signal-ramp" disabled={!ramp} onClick={() => ramp && onInspect(ramp.toLead)} aria-label={ramp ? `Inspect largest hourly change, ${(ramp.delta * 100).toFixed(1)} percentage points, at ${utcTime(ramp.toTime)} UTC` : 'Hourly change: insufficient coverage'}>
          <span className="signal-label"><Icon name="activity" size={16} />Largest hourly change<Icon name="arrow" size={15} /></span>
          <span className="signal-number">{ramp ? `${ramp.delta > 0 ? '+' : ''}${(ramp.delta * 100).toFixed(1)}` : '—'}<small>pp <span>per hour</span></small></span>
          <span className="signal-time">{ramp ? `${utcDate(ramp.fromTime)} ${utcClock(ramp.fromTime)} → ${utcTime(ramp.toTime)} UTC` : 'Two complete consecutive hours needed'}</span>
          <span className="signal-hint">{ramp ? Math.abs(ramp.delta) < 1e-8 ? 'The hourly forecast is flat over the covered period.' : ramp.delta < 0 ? 'Falling generation: review the following forecast hours.' : 'Rising generation: review the following forecast hours.' : 'Changes are measured only between adjacent hours.'}</span>
        </button>
      </div>
      <div className="output-strip"><div className="output-strip-heading"><span>TURBINE-AVERAGE OUTPUT</span><span>{signals.hours.length}/{signals.expectedHours} complete hours <span className="output-strip-divider">/</span> UTC</span></div>
        <svg role="img" aria-label={`Equal-weight normalized output across ${signals.assetCount} turbines; ${signals.hours.length} of ${signals.expectedHours} hours complete. Gaps are hatched.`} viewBox={`0 0 ${signals.expectedHours * 14} 56`} preserveAspectRatio="none">
          <defs><pattern id="missing-signal-hour" width="5" height="5" patternUnits="userSpaceOnUse"><path d="M0 5 5 0" stroke="var(--text-faint)" strokeWidth="1" opacity=".5" /></pattern></defs>
          {Array.from({ length: signals.expectedHours }, (_, index) => { const hour = hourByLead.get(index + 1); const height = hour ? 3 + hour.mean * 49 : 52; return <rect key={index} x={index * 14 + 1} y={54 - height} width="10" height={height} rx="2" fill={!hour ? 'url(#missing-signal-hour)' : index + 1 === activeLead ? 'var(--text)' : 'var(--accent)'} opacity={!hour ? .35 : index + 1 === activeLead ? 1 : .3 + hour.mean * .7}><title>{hour ? `${utcTime(hour.validTime)} UTC · ${(hour.mean * 100).toFixed(1)}%` : `Lead ${index + 1} · incomplete`}</title></rect>; })}
        </svg><div className="output-strip-axis"><span>+1h</span><span>+{signals.expectedHours / 2}h</span><span>+{signals.expectedHours}h</span></div>
      </div>
      {signals.hours.length < signals.expectedHours && <p className="operations-gap" role="status"><Icon name="warning" size={13} />{signals.expectedHours - signals.hours.length} incomplete hours excluded. Windows and ramps never cross missing hours.</p>}
      <p className="operations-method"><Icon name="info" size={13} />Equal weight per turbine; percentages are normalized output, not MW. Windows show interval boundaries. These signals do not establish safe maintenance conditions.</p>
    </>}
  </section>;
}
