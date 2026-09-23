import { useEffect, useMemo, useState } from 'react';
import { api, type EvidenceReport } from '../api';
import Icon from '../components/Icon';
import { bestSimpleBaseline, modelRole, poolMetrics, sameCoverage } from './metrics';
import './evidence.css';

type Props = { active?: boolean };

const number = new Intl.NumberFormat('en-GB');
const date = (value: string) => new Date(value).toLocaleDateString('en-GB', {
  timeZone: 'UTC', day: '2-digit', month: 'short', year: 'numeric',
});
const shortDate = (value: string) => new Date(value).toLocaleDateString('en-GB', {
  timeZone: 'UTC', day: '2-digit', month: 'short',
});
const score = (value: number) => value.toFixed(4);
const turbineName = (id: string) => /^turbine[-_]\d+$/.test(id) ? id.replace(/[-_]/g, ' ').replace(/^t/, 'T') : id;

function ExportLink({ compact = false }: { compact?: boolean }) {
  return <a className={`button ${compact ? 'quiet' : 'secondary'}`} href="/api/v1/evidence/export" download="wind-model-evidence.json"><Icon name="download" size={14} />Download evidence<span className="evidence-filetype">JSON</span></a>;
}

export default function EvidenceView({ active = true }: Props) {
  const [report, setReport] = useState<EvidenceReport | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [revision, setRevision] = useState(0);
  const [turbine, setTurbine] = useState('all');
  const [horizon, setHorizon] = useState('all');

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true); setError('');
    api.evidence().then(value => { if (!cancelled) setReport(value); })
      .catch(reason => { if (!cancelled) setError(reason instanceof Error ? reason.message : 'The evidence report could not be loaded.'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [active, revision]);

  const comparison = useMemo(() => report?.benchmark.models.map(model => {
    const metrics = model.metrics.filter(metric => (turbine === 'all' || metric.turbine_id === turbine) && (horizon === 'all' || metric.horizon === horizon));
    return { ...model, visibleMetrics: metrics, summary: turbine === 'all' && horizon === 'all' ? model.pooled : poolMetrics(metrics) };
  }) || [], [report, turbine, horizon]);
  const selected = comparison.find(model => model.selected || model.id === 'selected');
  const baseline = bestSimpleBaseline(comparison);
  const comparable = !!selected && !!baseline && sameCoverage(selected.visibleMetrics, baseline.visibleMetrics);
  const reduction = comparable && selected?.summary && baseline?.summary && baseline.summary.mae > 0
    ? (1 - selected.summary.mae / baseline.summary.mae) * 100 : null;
  const maxError = Math.max(...comparison.map(model => model.summary?.mae || 0), 0.0001);
  const turbines = [...new Set(report?.benchmark.models.flatMap(model => model.metrics.map(metric => metric.turbine_id)) || [])].sort();
  const candidate = report?.selection.candidates.find(item => item.selected);
  const folds = candidate?.folds || report?.selection.candidates[0]?.folds || [];

  return <section className="evidence-workspace" id="evidence" aria-labelledby="evidence-heading">
    <header className="evidence-heading">
      <div><span className="evidence-eyebrow"><Icon name="shield" size={14} />Evaluation notebook</span><h2 id="evidence-heading">Model evidence</h2><p>Measured results, reproducible decisions, and the limits that matter.</p></div>
      <div className="evidence-heading-actions">{report && <ExportLink />}<button type="button" className="icon-button" onClick={() => setRevision(value => value + 1)} disabled={loading} aria-label="Reload model evidence" title="Reload model evidence"><Icon name="refresh" className={loading ? 'spinning' : ''} /></button></div>
    </header>

    {error && <div className="evidence-state evidence-error" role="alert"><Icon name="warning" size={28} /><div><h3>Evidence could not be loaded</h3><p>{error}</p><p>{report ? 'The last loaded record remains visible below. Reload to check for an updated record.' : 'The workspace does not substitute demonstration scores for missing results.'}</p><button className="button secondary" type="button" onClick={() => setRevision(value => value + 1)} disabled={loading}><Icon name="refresh" />Try again</button></div></div>}
    {loading && !report && !error && <div className="evidence-state" role="status"><Icon name="refresh" size={26} className="spinning" /><div><h3>Reading the evaluation record</h3><p>Loading model comparisons and their source metadata.</p></div></div>}

    {report && <div className={loading ? 'evidence-content evidence-refreshing' : 'evidence-content'} aria-busy={loading}>
      <section className="evidence-hero" aria-labelledby="evidence-result-title">
        <div className="evidence-hero-copy"><span className="evidence-eyebrow">Chronological benchmark<span className="evidence-provisional"><span className="status-dot" />Provisional</span></span><h3 id="evidence-result-title">A forecast is only as useful<br className="evidence-desktop-break" /> as the evidence behind it.</h3><p>{report.benchmark.name}. All recorded models are compared on matching forecast targets, including training-only simple baselines.</p><div className="evidence-scope"><span><Icon name="calendar" size={14} />{shortDate(report.benchmark.first_issue)}–{date(report.benchmark.last_issue)} issue dates</span><span><Icon name="clock" size={14} />{report.benchmark.horizon_hours}-hour horizon</span></div></div>
        <div className="evidence-hero-result" aria-live="polite"><span className="evidence-result-label">{selected?.label || 'Selected model'} · mean absolute error</span><div className="evidence-primary-number">{selected?.summary ? score(selected.summary.mae) : '—'}<span>p.u.</span></div><div className={`evidence-result-change ${reduction != null && reduction >= 0 ? 'improved' : reduction != null ? 'regressed' : ''}`}><Icon name={reduction != null && reduction >= 0 ? 'chart' : 'info'} size={16} />{reduction == null ? 'Paired comparison unavailable' : `${Math.abs(reduction).toFixed(1)}% ${reduction >= 0 ? 'lower' : 'higher'} MAE than ${baseline?.label}`}</div><p>{selected?.summary ? `${number.format(selected.summary.samples)} scored issue / target pairs` : 'No observations in this selection'}{turbine !== 'all' || horizon !== 'all' ? ' · filtered below' : ' · both turbines, both lead windows'}</p><span className="evidence-unit-note">p.u. = normalized power. Lower error is better.</span></div>
      </section>

      <div className="evidence-caveat"><Icon name="info" size={17} /><p><strong>{report.benchmark.reused_comparison ? 'January is a reused comparison window.' : 'Provisional evaluation.'}</strong> {report.benchmark.reused_comparison ? 'It is not an untouched holdout. ' : ''}These results describe this benchmark model, not the currently selected forecast. No February accuracy score or calibrated confidence is claimed.</p></div>

      <section className="evidence-section" aria-labelledby="evidence-comparison-title">
        <div className="evidence-section-heading"><div><span className="evidence-eyebrow">01 / Benchmark</span><h3 id="evidence-comparison-title">Compare like for like.</h3><p>Same issue dates, horizons, and actual observations. Inspect each turbine and lead window.</p></div><div className="evidence-filters"><label>Turbine<select value={turbine} onChange={event => setTurbine(event.target.value)}><option value="all">All turbines</option>{turbines.map(id => <option key={id} value={id}>{turbineName(id)}</option>)}</select></label><label>Lead window<select value={horizon} onChange={event => setHorizon(event.target.value)}><option value="all">Full horizon</option><option value="1-24">1–24 hours</option><option value="25-48">25–48 hours</option></select></label></div></div>
        <div className="evidence-comparison-table table-scroll"><table><caption className="sr-only">Chronological model comparison. Errors are in normalized power units; lower values are better.</caption><thead><tr><th scope="col">Model</th><th scope="col">Mean absolute error <span>p.u.</span></th><th scope="col">RMSE <span>p.u.</span></th><th scope="col">Scored pairs</th></tr></thead><tbody>{comparison.map(model => <tr key={model.id} className={model.selected || model.id === 'selected' ? 'evidence-selected-row' : ''}><th scope="row"><span className="evidence-model-name">{model.label}{(model.selected || model.id === 'selected') && <span className="evidence-selected-tag">Selected</span>}</span><span className="evidence-model-role">{modelRole(model.id)}</span></th><td><div className="evidence-error-value"><strong>{model.summary ? score(model.summary.mae) : '—'}</strong><span className="evidence-error-track" aria-hidden="true"><span style={{ width: `${(model.summary?.mae || 0) / maxError * 100}%` }} /></span></div></td><td className="numeric">{model.summary ? score(model.summary.rmse) : '—'}</td><td className="numeric">{model.summary ? number.format(model.summary.samples) : '—'}</td></tr>)}</tbody></table></div>
        <div className="evidence-comparison-foot"><span><Icon name="layers" size={13} />{report.benchmark.feature_set} features</span><span>Training cutoff <strong>{date(report.benchmark.trained_through)}</strong></span><span>{number.format(report.benchmark.unscored_pairs)} pairs without actuals</span></div>
        <p className="evidence-method-note">All-turbine scores pool individual normalized turbine errors, without capacity weighting. RMSE is pooled from squared errors. Overlapping forecasts remain separate, correlated issue / target pairs.</p>
      </section>

      <section className="evidence-section" aria-labelledby="evidence-development-title">
        <div className="evidence-section-heading"><div><span className="evidence-eyebrow">02 / Development record</span><h3 id="evidence-development-title">A selection you can trace.</h3><p>{report.selection.objective}</p></div><span className="evidence-detail-label">{report.selection.candidates.length} candidates · {folds.length} chronological folds</span></div>
        <ol className="evidence-timeline"><li><span className="evidence-timeline-marker">1</span><div><strong>History begins</strong><span>{date(report.selection.first_training_origin)}</span><p>Training origins start here.</p></div></li><li><span className="evidence-timeline-marker">2</span><div><strong>Development folds</strong><span>{folds.length ? `${shortDate(folds[0].first_issue)} – ${date(folds[folds.length - 1].last_issue)}` : 'See candidate record'}</span><p>Compare fixed candidate settings.</p></div></li><li><span className="evidence-timeline-marker">3</span><div><strong>January comparison</strong><span>{shortDate(report.benchmark.first_issue)} – {date(report.benchmark.last_issue)}</span><p>{report.benchmark.reused_comparison ? 'Reused window; not untouched.' : 'See evaluation scope above.'}</p></div></li><li><span className="evidence-timeline-marker">4</span><div><strong>Final refit</strong><span>Through {date(report.refit.trained_through)}</span><p>{report.refit.evaluated ? 'Evaluation status in audit record.' : 'Refitted model has not been evaluated.'}</p></div></li></ol>
        <div className="table-scroll evidence-development-table"><table><caption className="sr-only">Candidate settings and chronological fold mean absolute errors, in normalized power units.</caption><thead><tr><th scope="col">Candidate / settings</th>{folds.map(fold => <th key={fold.name} scope="col">{fold.name}<span>MAE</span></th>)}<th scope="col">Pooled development <span>MAE</span></th></tr></thead><tbody>{report.selection.candidates.map(item => <tr key={item.name} className={item.selected ? 'evidence-selected-row' : ''}><th scope="row"><span className="evidence-model-name">{item.name}{item.selected && <Icon name="check" size={14} />}</span><span className="evidence-model-role">{item.feature_set} · {item.iterations} iterations · depth {item.depth} · {item.loss_function}</span></th>{folds.map(fold => <td key={fold.name} className="numeric">{item.folds.find(value => value.name === fold.name)?.pooled.mae.toFixed(4) ?? '—'}</td>)}<td className="numeric"><strong>{score(item.pooled.mae)}</strong></td></tr>)}</tbody></table></div>
        <div className="evidence-development-note"><Icon name="info" size={15} /><p>Selection recorded {date(report.selected_at)}. The final refit uses {number.format(report.refit.training_rows)} training rows. Benchmark scores above belong to the earlier evaluation model; they are not a measurement of the final refit.</p></div>
      </section>

      <section className="evidence-section evidence-audit-section" aria-labelledby="evidence-audit-title">
        <div className="evidence-section-heading"><div><span className="evidence-eyebrow">03 / Provenance & boundaries</span><h3 id="evidence-audit-title">Trust comes with a paper trail.</h3><p>Check what was verified, what was assumed, and what remains open.</p></div></div>
        <div className="evidence-audit-grid"><div className="evidence-checkpoints">{report.checkpoints.map(checkpoint => <article key={checkpoint.id} className={`evidence-checkpoint ${checkpoint.status}`}><span className="evidence-checkpoint-icon"><Icon name={checkpoint.status === 'verified' ? 'check' : checkpoint.status === 'provisional' ? 'info' : 'clock'} size={16} /></span><div><div className="evidence-checkpoint-heading"><h4>{checkpoint.title}</h4><span>{checkpoint.status}</span></div><p>{checkpoint.detail}</p></div></article>)}</div><aside className="evidence-data-record" aria-label="Data preparation record"><span className="evidence-eyebrow">Data preparation</span><strong>{number.format(report.data.complete_hours)}<span> complete turbine-hours</span></strong><dl><div><dt>SCADA timezone</dt><dd>{report.data.timezone}</dd></div><div><dt>Timestamp position</dt><dd>{report.data.timestamp_position}</dd></div><div><dt>Assumed latency</dt><dd>{report.data.latency_minutes} minutes</dd></div><div><dt>Preparation status</dt><dd>{report.data.provisional ? 'Provisional' : 'Recorded'}</dd></div></dl><p>These are the preparation settings used for this experiment. They do not establish missing station metadata.</p><div className="evidence-source-list">{report.data.sources.map(source => <div key={`${source.turbine_id}-${source.source_file}`}><strong>{turbineName(source.turbine_id)}</strong><span>{number.format(source.complete_hours)} complete / {number.format(source.incomplete_hours)} incomplete hours</span><span>{number.format(source.missing_slots)} missing sample slots</span><code title={source.source_file}>{source.source_file}</code></div>)}</div></aside></div>
        {report.weather && <article className="evidence-data-record" aria-label="Archived weather provenance"><span className="evidence-eyebrow">Archived forecast weather</span><h4>{report.weather.source} · {report.weather.model}</h4><dl><div><dt>Run initialization</dt><dd>{String(report.weather.run_hour_utc).padStart(2, '0')}:00 UTC</dd></div><div><dt>Daily forecast issue</dt><dd>{String(report.weather.issue_hour_utc).padStart(2, '0')}:00 UTC</dd></div><div><dt>Assumed publication delay</dt><dd>{report.weather.publication_delay_hours} hours</dd></div></dl><p>{report.weather.availability_basis}</p><p>Source SHA-256 <code>{report.weather.source_sha256}</code></p></article>}
        <div className="evidence-limitations"><h4><Icon name="warning" size={15} />Limits of this result</h4><ul>{report.limitations.map(limitation => <li key={limitation}>{limitation}</li>)}</ul></div>
      </section>

      <footer className="evidence-source-footer"><div><span className="evidence-eyebrow">Source record</span><strong>{report.source_file}</strong><span>SHA-256 <code title={report.source_sha256}>{report.source_sha256}</code></span></div><ExportLink compact /></footer>
    </div>}
  </section>;
}
