import type { ForecastRun } from '../api';
import { isActive, utcClock } from '../format';
import Icon from './Icon';

const steps = [
  { stage: 'validate', title: 'Validate' },
  { stage: 'weather', title: 'Weather' },
  { stage: 'predict', title: 'Predict' },
  { stage: 'analyse', title: 'Analyse' },
];

export default function AgentPanel({ run }: { run: ForecastRun | null }) {
  const events = run?.events || [];
  const status = !run ? 'Idle' : run.status === 'succeeded' ? 'Complete' : run.status === 'failed' ? 'Failed' : 'Running';
  return <section className="panel agent-panel" id="activity" aria-labelledby="agent-title">
    <div className="panel-heading"><h2 id="agent-title"><Icon name="activity" />Autonomous agent</h2><span className={`badge ${run?.status === 'failed' ? 'danger' : run?.status === 'succeeded' ? 'accent' : ''}`}><span className={`status-dot ${run?.status === 'succeeded' ? 'good' : ''}`} />{status}</span></div>
    <div className="agent-steps">{steps.map((step, i) => { const done = events.some(event => event.stage === step.stage); return <div key={step.stage} className={done ? 'step completed' : 'step'}><span>{done ? <Icon name="check" size={12} /> : String(i + 1).padStart(2, '0')}</span>{step.title}</div>; })}</div>
    <div className="agent-log" role="log" aria-label="Agent activity" aria-live="polite"><ol>{events.map((event, i) => <li key={`${run?.id}-${i}`}><time>{utcClock(event.at)}</time><span className={`event-marker ${event.stage === 'failed' ? 'danger' : event.stage === 'retry' ? 'warning' : ''}`} /><div><strong>{event.stage === 'complete' ? 'Forecast complete' : event.stage}</strong><p>{event.message}</p></div>{event.stage === 'complete' && <Icon name="check" size={14} />}</li>)}</ol>{!events.length && <div className="agent-empty"><Icon name="activity" size={26} /><strong>Standing by</strong><p>Weather retrieval, model execution, and quality checks appear here when a forecast runs.</p></div>}</div>
    <div className="panel-foot"><span><span className={`status-dot ${isActive(run?.status) ? 'good' : ''}`} />{isActive(run?.status) ? 'Workflow in progress' : 'Runs on forecast request'}</span><span>{events.length} events · UTC</span></div>
  </section>;
}
