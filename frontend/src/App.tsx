import { useEffect, useState } from 'react';
import Papa from 'papaparse';
import SiteMap from './SiteMap';
import { api, type Schema } from './api';

type Run = Schema<'ForecastRun'>;
type Replay = Schema<'BacktestRun'>;
const stamp = (s: string) => new Date(s).toLocaleString('ru-RU', { timeZone: 'UTC', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit' });
const iso = (value: string) => new Date(value + 'Z').toISOString();
const statusName = (s: string) => ({ queued: 'В очереди', running: 'Расчёт', succeeded: 'Готово', failed: 'Ошибка' }[s] ?? s);
const pending = (s?: string) => s === 'queued' || s === 'running';

function PowerChart({ points, actuals }: { points: Schema<'ForecastPoint'>[]; actuals: Schema<'Observation'>[] }) {
  const times = [...new Set(points.map(p => p.valid_time))].sort();
  const turbines = [...new Set(points.map(p => p.turbine_id))];
  const x = (t: string) => 48 + times.indexOf(t) / Math.max(1, times.length - 1) * 824;
  const y = (p: number) => 226 - p * 196;
  return <div className="chart-wrap"><svg viewBox="0 0 900 270" role="img" aria-label="Прогноз мощности по турбинам, доля номинала от 0 до 1">
    {[0, .25, .5, .75, 1].map(v => <g key={v}><line x1="48" x2="872" y1={y(v)} y2={y(v)} stroke="#dfebe7"/><text x="8" y={y(v) + 4}>{v.toFixed(2)}</text></g>)}
    {times.filter((_, i) => i % Math.max(1, Math.floor(times.length / 5)) === 0).map(t => <text key={t} x={x(t)} y="255" textAnchor="middle">{stamp(t)}</text>)}
    {turbines.map((id, i) => <g key={id}>
      <polyline fill="none" stroke={i ? '#e79952' : '#138d79'} strokeWidth="3" points={points.filter(p => p.turbine_id === id).map(p => `${x(p.valid_time)},${y(p.power_normalized)}`).join(' ')}/>
      {actuals.filter(p => p.turbine_id === id && times.includes(p.valid_time)).map(p => <circle key={p.valid_time} cx={x(p.valid_time)} cy={y(p.power_normalized)} r="3" fill={i ? '#a75b16' : '#143e38'}><title>{id}: факт {p.power_normalized.toFixed(3)}</title></circle>)}
    </g>)}
  </svg><div className="legend"><span><i className="dot"/>Турбина 1</span><span><i className="dot orange"/>Турбина 2</span><span>Точки — фактические наблюдения · UTC</span></div></div>;
}

export default function App() {
  const [tab, setTab] = useState<'forecast' | 'data' | 'weather'>('forecast');
  const [turbines, setTurbines] = useState<Schema<'Turbine'>[]>([]);
  const [models, setModels] = useState<Schema<'ModelInfo'>[]>([]);
  const [datasets, setDatasets] = useState<Schema<'DatasetInfo'>[]>([]);
  const [history, setHistory] = useState<Run[]>([]);
  const [replays, setReplays] = useState<Replay[]>([]);
  const [snapshots, setSnapshots] = useState<Schema<'WeatherSnapshot'>[]>([]);
  const [selected, setSelected] = useState(['turbine-1', 'turbine-2']);
  const [source, setSource] = useState<'demo' | 'archive'>('demo');
  const [modelId, setModelId] = useState('demo-power-curve');
  const [issued, setIssued] = useState('2026-01-31T07:00');
  const [horizon, setHorizon] = useState<24 | 48>(48);
  const [run, setRun] = useState<Run | null>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [actualId, setActualId] = useState('');
  const [actuals, setActuals] = useState<Schema<'Observation'>[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [endIssue, setEndIssue] = useState('2026-02-28T07:00');
  const [evalStart, setEvalStart] = useState('2026-02-01T00:00');
  const [evalEnd, setEvalEnd] = useState('2026-03-01T00:00');
  const [datasetId, setDatasetId] = useState('');
  const [cutoff, setCutoff] = useState('2026-01-30T23:00');
  const [algorithm, setAlgorithm] = useState<Schema<'TrainRequest'>['algorithm']>('binned-curve');
  const [trainingWeather, setTrainingWeather] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const [demoData, setDemoData] = useState(false);
  const [provenance, setProvenance] = useState('');
  const [weatherJson, setWeatherJson] = useState('');
  const [weatherTurbine, setWeatherTurbine] = useState('turbine-1');
  const [weatherRun, setWeatherRun] = useState('2026-01-31T00:00');

  async function reload() {
    const [ts, ms, ds, hs, bs, ws] = await Promise.all([api.turbines(), api.models(), api.datasets(), api.forecasts(), api.backtests(), api.weather()]);
    setTurbines(ts); setModels(ms); setDatasets(ds); setHistory(hs); setReplays(bs); setSnapshots(ws); setConnected(true);
  }
  async function act(fn: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('');
    try { await fn(); } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
    finally { setBusy(false); }
  }
  useEffect(() => { reload().catch(e => { setError(e.message); setConnected(false); }); }, []);
  useEffect(() => {
    if (!run || !pending(run.status)) return;
    let alive = true;
    const timer = window.setInterval(() => api.run(run.id).then(value => {
      if (!alive) return;
      setRun(value);
      if (!pending(value.status)) reload().catch(e => setError(e.message));
    }).catch(e => { if (alive) { setError(e.message); clearInterval(timer); } }), 1500);
    return () => { alive = false; clearInterval(timer); };
  }, [run?.id, run?.status]);
  useEffect(() => {
    if (!replay || !pending(replay.status)) return;
    let alive = true;
    const timer = window.setInterval(() => api.backtest(replay.id).then(value => {
      if (!alive) return;
      setReplay(value);
      if (!pending(value.status)) reload().catch(e => setError(e.message));
    }).catch(e => { if (alive) { setError(e.message); clearInterval(timer); } }), 1500);
    return () => { alive = false; clearInterval(timer); };
  }, [replay?.id, replay?.status]);
  useEffect(() => {
    setActuals([]);
    if (!actualId || !run?.result?.points.length) return;
    let alive = true;
    const times = run.result.points.map(p => p.valid_time).sort();
    api.observations(actualId, times[0], times[times.length - 1]).then(rows => { if (alive) setActuals(rows); }).catch(e => { if (alive) setError(e.message); });
    return () => { alive = false; };
  }, [actualId, run?.id, run?.status]);

  const request = (): Schema<'ForecastRequest'> => ({ turbine_ids: selected, issued_at: iso(issued), horizon_hours: horizon, weather_source: source, model_id: modelId });
  const points = run?.result?.points ?? [];
  const average = points.length ? points.reduce((a, p) => a + p.power_normalized, 0) / points.length : null;
  const demo = run?.result?.demo ?? (source === 'demo' || models.find(m => m.id === modelId)?.demo);

  async function importFile() {
    if (!file) throw new Error('Выберите CSV или JSON с каноническими наблюдениями');
    const text = await file.text();
    let body: Schema<'DatasetImport'>;
    if (file.name.endsWith('.json')) {
      body = JSON.parse(text);
    } else {
      const parsed = Papa.parse<Record<string, string>>(text, { header: true, skipEmptyLines: true });
      if (parsed.errors.length) throw new Error(parsed.errors[0].message);
      body = { name: file.name, demo: demoData, provenance, observations: parsed.data.map(row => ({
        turbine_id: row.turbine_id, valid_time: row.valid_time, available_at: row.available_at,
        wind_speed_ms: Number(row.wind_speed_ms || NaN), temperature_c: Number(row.temperature_c || NaN), power_normalized: Number(row.power_normalized || NaN)
      })) };
    }
    const result = await api.importDataset(body);
    setDatasetId(result.id); setNotice(`Импортировано ${result.row_count} наблюдений`); await reload();
  }

  return <div className="app">
    <aside className="sidebar"><a className="brand" href="#"><span className="brand-mark">↗</span><span>LOW PRIOR<small>WIND INTELLIGENCE</small></span></a>
      <div className="nav-label">РАБОЧАЯ ОБЛАСТЬ</div><nav aria-label="Главная навигация">
        <button className={tab === 'forecast' ? 'active' : ''} onClick={() => setTab('forecast')}>◷ <span>Прогноз и replay</span></button>
        <button className={tab === 'data' ? 'active' : ''} onClick={() => setTab('data')}>▤ <span>Данные и модели</span></button>
        <button className={tab === 'weather' ? 'active' : ''} onClick={() => setTab('weather')}>◎ <span>Архив погоды</span></button>
      </nav><div className="sidebar-bottom"><span className={'connection ' + (connected ? 'online' : '')}>● {connected ? 'API подключён' : 'Ожидание API'}</span><p>Шелекский коридор<br/>2 ветровые турбины</p><small>SCADA UTC+6 · интерфейс UTC</small></div>
    </aside>
    <main><header><div><p className="eyebrow">LOW PRIOR-IT / HACKALEM AI</p><h1>{tab === 'forecast' ? 'Ветер. Данные. Прогноз.' : tab === 'data' ? 'Основа каждого прогноза' : 'Погода с историей'}</h1><p className="muted">{tab === 'forecast' ? 'Почасовая мощность двух турбин на следующие 24–48 часов.' : tab === 'data' ? 'Наблюдения, воспроизводимое обучение и дата отсечения.' : 'Проверяемое происхождение и доступность на момент выпуска.'}</p></div><button className="secondary" disabled={busy} onClick={() => act(reload)}>↻ Обновить</button></header>
      {error && <div className="alert error" role="alert">{error}<button aria-label="Закрыть ошибку" onClick={() => setError('')}>×</button></div>}
      {notice && <div className="alert" role="status">{notice}</div>}
      {tab === 'forecast' && <>
        <section className="panel controls"><div className="section-title"><h2>Новый прогноз</h2><span className="tag">Все даты в UTC</span></div>
          <div className="form-grid"><fieldset><legend>Турбины</legend>{turbines.map(t => <label className="check" key={t.id}><input type="checkbox" checked={selected.includes(t.id)} onChange={e => setSelected(e.target.checked ? [...selected, t.id] : selected.filter(id => id !== t.id))}/>{t.name}</label>)}</fieldset>
            <label>Время выпуска<input type="datetime-local" step="3600" value={issued} onChange={e => setIssued(e.target.value)}/></label>
            <label>Горизонт<select value={horizon} onChange={e => setHorizon(Number(e.target.value) as 24 | 48)}><option value={24}>24 часа</option><option value={48}>48 часов</option></select></label>
            <label>Погода<select value={source} onChange={e => setSource(e.target.value as 'demo' | 'archive')}><option value="demo">Synthetic demo</option><option value="archive">Проверенный архив</option></select></label>
            <label>Модель<select value={modelId} onChange={e => setModelId(e.target.value)}>{models.map(m => <option key={m.id} value={m.id}>{m.id === 'demo-power-curve' ? 'Demo power curve' : `${m.algorithm} · ${m.id.slice(-6)}`}{m.demo ? ' · DEMO' : ''}</option>)}</select></label>
            <button className="primary" disabled={busy || !selected.length || pending(run?.status)} onClick={() => act(async () => { setRun(await api.forecast(request())); })}>Запустить прогноз ↗</button>
          </div>
        </section>
        <div className={'mode-banner ' + (demo ? 'demo' : '')}><span>{demo ? 'DEMO' : 'ARCHIVE'}</span><p>{demo ? 'Синтетическая погода или демонстрационная модель. Результат показывает работу системы и не является конкурсным прогнозом.' : 'Погода допускается только с подтверждением публикации до времени выпуска.'}</p></div>
        <div className="stats"><div><span>Средняя доля мощности</span><strong>{average === null ? '—' : average.toFixed(3)}<small> p.u.</small></strong><p>По выбранным турбинам и часам</p></div><div><span>Почасовых значений</span><strong>{points.length || '—'}</strong><p>{run ? `${run.request.horizon_hours} часов × ${run.request.turbine_ids.length} турбины` : 'Выберите параметры прогноза'}</p></div><div><span>Статус расчёта</span><strong className="status-value">{run ? statusName(run.status) : 'Готов к запуску'}</strong><p>Сохранение результатов в SQLite</p></div></div>
        <section className="panel"><div className="section-title"><div><p className="eyebrow">HOURLY OUTLOOK</p><h2>Прогноз выработки</h2></div><div className="actions">{run && <button className="secondary" disabled={busy || pending(run.status)} onClick={() => act(async () => { const next = await api.refresh(run.id); setNotice(next.id === run.id ? 'Входы не изменились: сохранён прежний результат' : 'Новые входы: создан новый прогноз'); setRun(next); })}>Проверить новые входы</button>}{run?.status === 'succeeded' && <a className="button" href={api.exportUrl('forecasts', run.id)}>↓ CSV</a>}</div></div>
          <label className="inline-label">Фактические наблюдения<select value={actualId} onChange={e => setActualId(e.target.value)}><option value="">Без фактов</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}{d.demo ? ' · DEMO' : ''}</option>)}</select></label>
          {run?.error && <div className="alert error">{run.error.message}</div>}
          {points.length ? <><PowerChart points={points} actuals={actuals}/>{actualId && !actuals.length && <p className="muted">В выбранном наборе нет фактов за эти часы. Точность не рассчитана.</p>}<details><summary>Почасовая таблица · {points.length} строк</summary><div className="table-scroll"><table><thead><tr><th>UTC, конец часа</th><th>Турбина</th><th>Горизонт</th><th>Прогноз, p.u.</th><th>Факт, p.u.</th></tr></thead><tbody>{points.map(p => <tr key={p.turbine_id + p.valid_time}><td>{stamp(p.valid_time)}</td><td>{p.turbine_id}</td><td>+{p.lead_hours} ч</td><td>{p.power_normalized.toFixed(4)}</td><td>{actuals.find(a => a.turbine_id === p.turbine_id && a.valid_time === p.valid_time)?.power_normalized.toFixed(4) ?? '—'}</td></tr>)}</tbody></table></div></details></> : <div className="empty"><span>〰</span><h3>{pending(run?.status) ? 'Строим почасовой прогноз…' : 'Прогноз появится здесь'}</h3><p>Запустите расчёт с параметрами выше или откройте сохранённый.</p></div>}
        </section>
        {run?.result && <section className="panel"><h2>Происхождение и решения агента</h2><div className="provenance-grid">{run.result.weather.map(w => <div key={w.id}><span className="tag">{w.verification}</span><h3>{w.turbine_id} · {w.weather_model}</h3><p>Запуск: {stamp(w.run_init)} UTC<br/>Доступен: {w.available_at ? stamp(w.available_at) + ' UTC' : 'не подтверждено'}<br/>Высота ветра: {w.wind_height_m} м</p><small>{w.availability_evidence || w.source}</small></div>)}</div><ul className="warnings">{run.result.warnings.map((w, i) => <li key={i}>{w}</li>)}</ul><ol className="events">{(run.events ?? []).map((event, i) => <li key={i}><b>{event.step}</b><span>{event.message}</span></li>)}</ol><small className="hash">Fingerprint: {run.fingerprint}</small></section>}
        <section className="panel"><div className="section-title"><div><p className="eyebrow">ROLLING REPLAY</p><h2>Проверка на истории</h2></div>{replay?.status === 'succeeded' && <a className="button" href={api.exportUrl('backtests', replay.id)}>↓ Replay CSV</a>}</div><p className="muted">Первый выпуск — из формы прогноза. Выпуски повторяются ежедневно; конец окна оценки не включается. Перекрывающиеся прогнозы сохраняются отдельно.</p><div className="form-grid"><label>Последний выпуск UTC<input type="datetime-local" value={endIssue} step="3600" onChange={e => setEndIssue(e.target.value)}/></label><label>Оценка с UTC<input type="datetime-local" value={evalStart} step="3600" onChange={e => setEvalStart(e.target.value)}/></label><label>Оценка до UTC<input type="datetime-local" value={evalEnd} step="3600" onChange={e => setEvalEnd(e.target.value)}/></label><button className="primary" disabled={busy || !selected.length || pending(replay?.status)} onClick={() => act(async () => { setReplay(await api.replay({ ...request(), end_issue_at: iso(endIssue), evaluation_start: iso(evalStart), evaluation_end: iso(evalEnd), actual_dataset_id: actualId || null })); })}>Run daily replay ↗</button></div>
          {replay && <><p role="status">{statusName(replay.status)} · {replay.completed}/{replay.total} выпусков {replay.demo && <span className="tag">DEMO</span>}</p><progress value={replay.completed} max={replay.total}/>{replay.error && <div className="alert error">{replay.error.message}</div>}{!!replay.metrics?.length && <div className="table-scroll"><table><thead><tr><th>Турбина</th><th>Горизонт</th><th>MAE</th><th>RMSE</th><th>Оценено</th><th>Без фактов</th></tr></thead><tbody>{replay.metrics.map(m => <tr key={m.turbine_id + m.horizon}><td>{m.turbine_id}</td><td>{m.horizon} ч</td><td>{m.mae?.toFixed(4) ?? '—'}</td><td>{m.rmse?.toFixed(4) ?? '—'}</td><td>{m.scored}/{m.predicted}</td><td>{m.missing}</td></tr>)}</tbody></table></div>}</>}
        </section>
        <div className="two-columns"><section className="panel"><h2>Последние прогнозы</h2>{!history.length && <p className="muted">Сохранённых расчётов пока нет.</p>}<div className="history">{history.map(r => <button key={r.id} onClick={() => setRun(r)}><span>{stamp(r.request.issued_at)} UTC<small>{r.request.weather_source} · {r.request.horizon_hours} ч · {r.id.slice(-6)}</small></span><span className="tag">{statusName(r.status)}</span></button>)}</div></section><section className="panel"><h2>История replay</h2>{!replays.length && <p className="muted">Запустите дневную проверку на истории.</p>}<div className="history">{replays.map(r => <button key={r.id} onClick={() => setReplay(r)}><span>{stamp(r.request.issued_at)}<small>{r.completed}/{r.total} выпусков · {r.demo ? 'DEMO' : 'ARCHIVE'}</small></span><span className="tag">{statusName(r.status)}</span></button>)}</div></section></div>
      </>}
      {tab === 'data' && <>
        <section className="panel"><h2>Импорт наблюдений</h2><p className="muted">Канонический CSV или JSON. Мощность — доля номинала [0, 1], время — конец часа с часовым поясом. Исходную SCADA сначала конвертируйте командой scripts/convert_scada.py.</p><code className="contract">turbine_id,valid_time,available_at,wind_speed_ms,temperature_c,power_normalized</code><div className="form-grid"><label>Файл<input type="file" accept=".csv,.json" onChange={e => setFile(e.target.files?.[0] ?? null)}/></label><label>Происхождение и преобразования (CSV)<input value={provenance} onChange={e => setProvenance(e.target.value)} placeholder="Источник, шкала времени, задержка"/></label><label className="check"><input type="checkbox" checked={demoData} onChange={e => setDemoData(e.target.checked)}/>Искусственные данные (CSV)</label><button className="primary" disabled={busy || !file} onClick={() => act(importFile)}>Импортировать</button></div></section>
        <section className="panel"><h2>Обучение модели</h2><p className="muted">Обучение учитывает дату наблюдения и его доступность. Weather ridge требует проверенных погодных снимков. Прогнозы кандидата ограничиваются диапазоном [0, 1]; интервалы неопределённости пока не калиброваны.</p><div className="form-grid"><label>Набор данных<select value={datasetId} onChange={e => setDatasetId(e.target.value)}><option value="">Выберите набор</option>{datasets.map(d => <option key={d.id} value={d.id}>{d.name}</option>)}</select></label><label>Дата отсечения UTC<input type="datetime-local" step="3600" value={cutoff} onChange={e => setCutoff(e.target.value)}/></label><label>Алгоритм<select value={algorithm} onChange={e => setAlgorithm(e.target.value as typeof algorithm)}><option value="binned-curve">Binned power curve</option><option value="persistence">Persistence baseline</option><option value="weather-ridge">Weather ridge candidate</option></select></label><button className="primary" disabled={busy || !datasetId} onClick={() => act(async () => { const model = await api.train({ dataset_id: datasetId, trained_through: iso(cutoff), algorithm, weather_snapshot_ids: trainingWeather.split(',').map(s => s.trim()).filter(Boolean) }); setModelId(model.id); setNotice(`Модель обучена: ${model.training_rows} строк`); await reload(); })}>Обучить модель</button></div>{algorithm === 'weather-ridge' && <label>ID проверенных снимков, через запятую<textarea value={trainingWeather} onChange={e => setTrainingWeather(e.target.value)}/></label>}</section>
        <section className="panel"><h2>Наборы данных · {datasets.length}</h2><div className="table-scroll"><table><thead><tr><th>Название</th><th>Строк</th><th>Период UTC</th><th>Происхождение</th></tr></thead><tbody>{datasets.map(d => <tr key={d.id}><td>{d.name} {d.demo && <span className="tag">DEMO</span>}</td><td>{d.row_count.toLocaleString()}</td><td>{stamp(d.start)} — {stamp(d.end)}</td><td>{d.provenance}</td></tr>)}</tbody></table></div></section>
        <section className="panel"><h2>Модели · {models.length}</h2>{models.map(m => <div className="model-row" key={m.id}><h3>{m.algorithm} {m.demo && <span className="tag">DEMO</span>}</h3><code>{m.id}</code><p>Отсечение: {m.trained_through ? stamp(m.trained_through) + ' UTC' : 'не обучалась'} · Строк: {m.training_rows}</p>{m.warnings?.map(w => <p key={w} className="muted">{w}</p>)}</div>)}</section>
      </>}
      {tab === 'weather' && <>
        <section className="panel"><h2>Турбины на площадке</h2><SiteMap turbines={turbines}/><div className="provenance-grid">{turbines.map(t => <article key={t.id}><h3>{t.name}</h3><p>{t.latitude}, {t.longitude}</p><a href={`https://www.openstreetmap.org/?mlat=${t.latitude}&mlon=${t.longitude}#map=16/${t.latitude}/${t.longitude}`} target="_blank" rel="noreferrer">Открыть на карте ↗</a><p>Номинал: {t.capacity_kw ?? 'не задан условием'}{t.capacity_kw ? ' кВт' : ''}<br/>Ступица: {t.hub_height_m ?? 'не задана условием'}{t.hub_height_m ? ' м' : ''}</p><small>{t.metadata_note}</small></article>)}</div></section>
        <section className="panel"><h2>Скачать кандидат Open-Meteo</h2><p className="muted">Скачивание не подтверждает доступность в прошлом. Новый снимок сохраняется как unverified с исходным ответом провайдера.</p><div className="form-grid"><label>Турбина<select value={weatherTurbine} onChange={e => setWeatherTurbine(e.target.value)}>{turbines.map(t => <option key={t.id} value={t.id}>{t.name}</option>)}</select></label><label>Инициализация запуска UTC<input type="datetime-local" step="3600" value={weatherRun} onChange={e => setWeatherRun(e.target.value)}/></label><button className="primary" disabled={busy} onClick={() => act(async () => { const s = await api.fetchWeather({ turbine_id: weatherTurbine, run_init: iso(weatherRun), weather_model: 'ecmwf_ifs' }); setWeatherJson(JSON.stringify(s, null, 2)); setNotice('Кандидат сохранён. Историческая доступность не подтверждена.'); await reload(); })}>Скачать ECMWF</button></div></section>
        <section className="panel"><h2>Импорт снимка / отдельной ревизии</h2><p className="muted">Для verified нужны новый ID, kind=forecast, исторический available_at и документированное availability_evidence. Существующая запись неизменяема. Поле evidence фиксирует ваше заключение; приложение не удостоверяет его автоматически.</p><label>JSON WeatherSnapshot<textarea className="json-editor" value={weatherJson} onChange={e => setWeatherJson(e.target.value)} placeholder='{"id": "weather-…", …}'/></label><button className="primary" disabled={busy || !weatherJson} onClick={() => act(async () => { await api.importWeather(JSON.parse(weatherJson)); setNotice('Снимок сохранён'); await reload(); })}>Импортировать новую запись</button></section>
        <section className="panel"><h2>Сохранённые снимки · {snapshots.length}</h2>{!snapshots.length && <p className="muted">Архив пуст. Демо-погода создаётся независимо при расчёте.</p>}<div className="table-scroll"><table><thead><tr><th>ID / турбина</th><th>Модель</th><th>Запуск UTC</th><th>Доступен UTC</th><th>Статус</th><th>Часов</th></tr></thead><tbody>{snapshots.map(s => <tr key={s.id}><td><button className="text-button" onClick={() => setWeatherJson(JSON.stringify(s, null, 2))}>{s.id}</button><small>{s.turbine_id}</small></td><td>{s.weather_model}</td><td>{stamp(s.run_init)}</td><td>{s.available_at ? stamp(s.available_at) : 'не подтверждено'}</td><td><span className="tag">{s.verification}</span></td><td>{s.points.length}</td></tr>)}</tbody></table></div></section>
      </>}
      <footer>LOW PRIOR WIND <span>Нормализованная мощность · без предположений о МВт</span><a href="/api/v1/turbines" target="_blank" rel="noreferrer">API</a></footer>
    </main>
  </div>;
}
