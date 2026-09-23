import { useState } from 'react';
import type { BacktestRun, DatasetInfo, ModelInfo, Turbine } from '../api';
import { isActive, utcDate, utcTime } from '../format';
import Icon from './Icon';

type Props = {
  backtest: BacktestRun | null;
  datasets: DatasetInfo[];
  models: ModelInfo[];
  turbines: Turbine[];
  disabled: boolean;
  onReplay: (dataset: string | null) => void;
};

export default function ReplayPanel({ backtest, datasets, models, turbines, disabled, onReplay }: Props) {
  const [dataset, setDataset] = useState('');
  const model = models.find(m => m.id === backtest?.request.model_id);
  const metrics = backtest?.metrics || [];
  const scored = backtest?.scored_points || 0;
  const unscored = backtest?.unscored_points || 0;
  const total = scored + unscored;
  const isDemo = backtest?.is_demo || backtest?.request.weather_source === 'demo';

  return <section className="panel replay-panel" id="replay" aria-labelledby="replay-title">
    <div className="panel-heading"><div className="heading-group"><h2 id="replay-title"><Icon name="bars" />Model & backtest metrics</h2><span className="subtle-label">February 2026</span></div><div className="panel-actions">{backtest && <span className={`badge ${backtest.status === 'failed' ? 'danger' : ''}`}>{isDemo ? 'Demo · ' : ''}{backtest.status}</span>}{backtest?.status === 'succeeded' && <a className="button quiet" href={`/api/v1/backtests/${backtest.id}/export`}><Icon name="download" />Export replay</a>}</div></div>
    <div className="replay-layout"><div className="replay-controls"><span className="section-label">ROLLING EVALUATION</span><h3>One forecast. Every day.</h3><p>29 issue dates · 31 Jan–28 Feb · 12:00 UTC<br />17:00 Kazakhstan · target window: February UTC</p><label className="control-field">Actual observations<select value={dataset} onChange={e => setDataset(e.target.value)} disabled={disabled}><option value="">No actuals attached</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.is_demo ? 'Demo · ' : ''}{d.name}</option>)}</select></label><button className="button secondary" disabled={disabled} onClick={() => onReplay(dataset || null)}><Icon name="refresh" className={isActive(backtest?.status) ? 'spinning' : ''} />{isActive(backtest?.status) ? 'Replaying forecasts…' : 'Run February replay'}</button><span className="small muted">Uses the selected turbines, model and horizon. Daily issue time is fixed at 12:00 UTC.</span></div>
      <div className="replay-results"><div className="metric-strip"><div><span>Daily forecasts</span><strong>{backtest ? backtest.forecast_ids?.length || 0 : '—'}<small>/29</small></strong></div><div><span>Scored predictions</span><strong>{backtest ? scored.toLocaleString() : '—'}</strong></div><div><span>Scoring coverage</span><strong>{total ? `${(scored / total * 100).toFixed(1)}%` : '—'}</strong></div><div><span>Without actuals</span><strong>{backtest ? unscored.toLocaleString() : '—'}</strong></div></div>
        {backtest?.error && <div className="notice danger" role="alert"><Icon name="warning" /><span>{backtest.error}</span></div>}
        <div className="table-scroll"><table className="metrics-table"><thead><tr><th scope="col">Turbine</th><th scope="col">Lead time</th><th scope="col">MAE <span>p.u.</span></th><th scope="col">RMSE <span>p.u.</span></th><th scope="col">Samples</th></tr></thead><tbody>{metrics.length ? metrics.map(metric => <tr key={`${metric.turbine_id}-${metric.horizon}`}><td>{turbines.find(t => t.id === metric.turbine_id)?.name || metric.turbine_id}</td><td>{metric.horizon} h</td><td className="numeric">{metric.mae.toFixed(4)}</td><td className="numeric">{metric.rmse.toFixed(4)}</td><td className="numeric">{metric.samples.toLocaleString()}</td></tr>) : <><tr className="unscored-row"><td>All turbines</td><td>1–24 h</td><td>—</td><td>—</td><td>—</td></tr><tr className="unscored-row"><td>All turbines</td><td>25–48 h</td><td>—</td><td>—</td><td>—</td></tr></>}</tbody></table></div>
        {!metrics.length && <div className="metric-empty"><Icon name="info" /><span>{isActive(backtest?.status) ? 'Daily forecasts are running. Scores appear after evaluation completes.' : 'Accuracy metrics require matching actual observations. Missing values are never scored as zero.'}</span></div>}
        <div className="replay-metadata"><span>Model <strong>{model?.algorithm || backtest?.request.model_id || 'No replay selected'}</strong></span><span>Training cutoff <strong>{model?.trained_through ? `${utcDate(model.trained_through)} UTC` : '—'}</strong></span>{backtest && <span>Issued <strong>{utcTime(backtest.created_at)} UTC</strong></span>}</div>
      </div></div>
  </section>;
}
