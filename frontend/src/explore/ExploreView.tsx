import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useState, type ReactNode } from 'react';
import { api, type EnergyAsset } from '../api';
import Icon from '../components/Icon';
import { energyTypes, forecastIds, groupSites, type AssetSite, type Country, type EnergyFilter } from './catalog';
import './explore.css';

const GlobeCanvas = lazy(() => import('./GlobeCanvas'));
type Props = { active: boolean; forecastingDisabled: boolean; onOpenForecast: (ids: string[]) => void };

function GlobeFallback() {
  return <div className="globe-fallback"><Icon name="globe" size={60} /><strong>Explore from the station directory</strong><p>The 3D view is unavailable on this device. Country search and station selection are still available.</p></div>;
}

class GlobeBoundary extends Component<{ children: ReactNode; onError: () => void }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch() { this.props.onError(); }
  render() { return this.state.failed ? <GlobeFallback /> : this.props.children; }
}

export default function ExploreView({ active, forecastingDisabled, onOpenForecast }: Props) {
  const [assets, setAssets] = useState<EnergyAsset[]>([]);
  const [countries, setCountries] = useState<Country[]>([]);
  const [country, setCountry] = useState<Country | null>(null);
  const [siteId, setSiteId] = useState<string | null>(null);
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState<EnergyFilter>('all');
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(true);
  const [assetError, setAssetError] = useState('');
  const [mapError, setMapError] = useState(false);
  const [revision, setRevision] = useState(0);
  const [reducedMotion, setReducedMotion] = useState(() => window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [rotating, setRotating] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches);
  const [webgl, setWebgl] = useState<boolean | null>(null);
  const [globeReady, setGlobeReady] = useState(false);
  const [resetKey, setResetKey] = useState(0);

  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => { setReducedMotion(preference.matches); if (preference.matches) setRotating(false); };
    preference.addEventListener('change', update);
    try {
      const context = document.createElement('canvas').getContext('webgl2');
      setWebgl(!!context);
      context?.getExtension('WEBGL_lose_context')?.loseContext();
    } catch { setWebgl(false); }
    return () => preference.removeEventListener('change', update);
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setMapError(false);
    fetch(`${import.meta.env.BASE_URL}geo/countries.geojson`, { signal: controller.signal })
      .then(response => { if (!response.ok) throw new Error('Country boundaries unavailable'); return response.json(); })
      .then(data => { if (!controller.signal.aborted) setCountries(data.features); })
      .catch(() => { if (!controller.signal.aborted) setMapError(true); });
    return () => controller.abort();
  }, [revision]);

  useEffect(() => {
    if (!active) return;
    let cancelled = false;
    setLoading(true); setAssetError('');
    api.assets().then(rows => { if (!cancelled) setAssets(rows); })
      .catch(error => { if (!cancelled) setAssetError(error.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [active, revision]);

  const sites = useMemo(() => groupSites(assets), [assets]);
  const countryOptions = useMemo(() => {
    const options = [...countries];
    for (const site of sites) {
      if (site.countryCode && !options.some(c => c.properties.code === site.countryCode)) options.push({
        type: 'Feature', geometry: { type: 'Polygon', coordinates: [] },
        properties: { code: site.countryCode, name: site.countryName, lat: site.lat || 0, lng: site.lng || 0, span: 35 },
      });
    }
    return options.sort((a, b) => a.properties.name.localeCompare(b.properties.name));
  }, [countries, sites]);
  const visibleSites = useMemo(() => sites.filter(s => (!country || s.countryCode === country.properties.code) && (filter === 'all' || s.energyType === filter)), [sites, country, filter]);
  const currentSite = visibleSites.find(s => s.id === siteId) || null;
  const countryAssets = assets.filter(asset => !country || asset.country_code === country.properties.code);
  const availableCountries = countryOptions.filter(c => assets.some(asset => asset.country_code === c.properties.code));
  const searchedCountries = countryOptions.filter(c => c.properties.name.toLowerCase().includes(search.trim().toLowerCase()) || c.properties.code.toLowerCase() === search.trim().toLowerCase());
  const chosenIds = currentSite ? forecastIds(currentSite.assets).filter(id => selected.includes(id)) : [];
  const stopRotation = useCallback(() => setRotating(false), []);
  const onReady = useCallback(() => setGlobeReady(true), []);
  const onUnavailable = useCallback(() => setWebgl(false), []);

  const chooseCountry = useCallback((next: Country) => {
    setCountry(next); setSiteId(null); setSelected([]); setSearch(''); setRotating(false); setResetKey(value => value + 1);
  }, []);
  const chooseSite = useCallback((site: AssetSite) => {
    const parent = countryOptions.find(c => c.properties.code === site.countryCode);
    if (parent) setCountry(parent);
    setFilter(site.energyType); setSiteId(site.id); setSelected(forecastIds(site.assets)); setRotating(false); setSearch('');
    setResetKey(value => value + 1);
  }, [countryOptions]);
  function world() { setCountry(null); setSiteId(null); setSelected([]); setSearch(''); setResetKey(value => value + 1); }

  return <section className="explore-workspace" id="explore" aria-labelledby="explore-heading">
    <div className="explore-heading"><div><div className="section-context"><span className="context-mark" /><h2 id="explore-heading">Energy explorer</h2><span className="badge">Asset network</span></div><p>Find a location. Select your assets. See what comes next.</p></div><div className="explore-summary"><span><strong>{assets.length}</strong> connected assets</span><span><strong>{availableCountries.length}</strong> countries</span></div></div>
    <div className="explore-typebar" aria-label="Filter by energy source"><button className={filter === 'all' ? 'energy-filter active' : 'energy-filter'} aria-pressed={filter === 'all'} onClick={() => { setFilter('all'); setSiteId(null); }}><Icon name="layers" />All energy<span>{countryAssets.length}</span></button>{energyTypes.map(type => {
      const count = countryAssets.filter(a => a.energy_type === type.id).length;
      return <button key={type.id} className={filter === type.id ? 'energy-filter active' : 'energy-filter'} aria-pressed={filter === type.id} onClick={() => { setFilter(type.id); setSiteId(null); }}><Icon name={type.icon} />{type.name}<span>{count}</span></button>;
    })}<span className="typebar-note">Wind forecasting available</span></div>

    <div className="explore-layout">
      <div className="globe-panel panel">
        <nav className="explore-breadcrumb" aria-label="Location"><button onClick={world}><Icon name="globe" size={13} />World</button>{country && <><Icon name="chevron" size={12} /><button onClick={() => chooseCountry(country)}>{country.properties.name}</button></>}{currentSite && <><Icon name="chevron" size={12} /><span>{currentSite.name}</span></>}</nav>
        <div className="globe-stage">
          {webgl === false ? <GlobeFallback /> : webgl && <GlobeBoundary onError={onUnavailable}><Suspense fallback={<div className="globe-loading"><Icon name="globe" size={36} /><span>Loading Earth…</span></div>}><GlobeCanvas countries={countries} country={country} sites={visibleSites} site={currentSite} active={active} rotating={rotating} reducedMotion={reducedMotion} resetKey={resetKey} onCountry={chooseCountry} onSite={chooseSite} onInteraction={stopRotation} onReady={onReady} onUnavailable={onUnavailable} /></Suspense></GlobeBoundary>}
          {webgl && !globeReady && <span className="globe-loading-label" role="status">Preparing geographic view</span>}
          <div className="globe-orientation" aria-hidden="true"><span>N</span><span className="orientation-line" />{country ? country.properties.code : 'EARTH'}</div>
        </div>
        <div className="globe-toolbar"><div className="globe-controls"><button className="button quiet" disabled={!!country || reducedMotion || !webgl} onClick={() => setRotating(value => !value)} aria-label={rotating ? 'Pause globe rotation' : 'Resume globe rotation'}><Icon name={rotating ? 'pause' : 'play'} size={12} />{reducedMotion ? 'Reduced motion' : country ? 'Rotation paused' : rotating ? 'Pause rotation' : 'Rotate'}</button><button className="icon-button" title="Reset globe view" aria-label="Reset globe view" onClick={world}><Icon name="target" size={14} /></button></div><span className="globe-hint">Drag to rotate · Scroll to zoom</span><a href="https://www.naturalearthdata.com/" target="_blank" rel="noreferrer">Natural Earth<Icon name="external" size={10} /></a></div>
      </div>

      <aside className="explore-directory panel" aria-label="Country and station directory">
        <div className="directory-heading"><span className="section-label">STATION DIRECTORY</span><span className="badge">{country ? country.properties.code : 'Global'}</span></div>
        <label className="country-search"><Icon name="search" size={16} /><span className="sr-only">Search countries</span><input type="search" value={search} onChange={event => setSearch(event.target.value)} placeholder="Search countries" aria-label="Search countries" /></label>
        <label className="control-field country-select"><span>Country</span><select aria-label="Select country" value={country?.properties.code || ''} onChange={event => { const next = countryOptions.find(c => c.properties.code === event.target.value); if (next) chooseCountry(next); else world(); }}><option value="">All countries</option>{countryOptions.map(c => <option key={c.properties.code} value={c.properties.code}>{c.properties.name}</option>)}</select></label>
        {search.trim() && <div className="country-results" aria-label="Matching countries">{searchedCountries.length ? searchedCountries.map(c => <button key={c.properties.code} onClick={() => chooseCountry(c)}><span>{c.properties.name}</span><span className="subtle-label">{assets.filter(a => a.country_code === c.properties.code).length} assets</span></button>) : <p>No matching countries.</p>}</div>}
        {mapError && <p className="directory-message">Country boundaries could not load. Connected locations remain available. <button onClick={() => setRevision(v => v + 1)}>Retry</button></p>}
        <div className="directory-location"><h3>{country?.properties.name || 'Connected locations'}</h3><p>{country ? 'Explore the energy assets in this country.' : 'Select a country on Earth or start with a connected site.'}</p></div>
        {!country && availableCountries.length > 0 && <div className="connected-countries">{availableCountries.map(c => <button key={c.properties.code} onClick={() => chooseCountry(c)}><span className="country-code">{c.properties.code}</span><span>{c.properties.name}<small>{assets.filter(a => a.country_code === c.properties.code).length} connected assets</small></span><Icon name="chevron" size={13} /></button>)}</div>}
        {loading && <p className="directory-message" role="status">Loading asset registry…</p>}
        {assetError && <div className="directory-message danger" role="alert"><span>Asset registry unavailable. {assetError}</span><button onClick={() => setRevision(v => v + 1)}>Reconnect</button></div>}
        <div className="site-list-heading"><span>{filter === 'all' ? 'All energy sites' : `${energyTypes.find(t => t.id === filter)?.name} sites`}</span><span>{visibleSites.length}</span></div>
        <div className="site-list">{visibleSites.map(site => <button key={site.id} className={`site-card ${site.id === currentSite?.id ? 'selected' : ''}`} onClick={() => chooseSite(site)} aria-pressed={site.id === currentSite?.id}><span className="site-icon"><Icon name={energyTypes.find(t => t.id === site.energyType)!.icon} size={20} /></span><span><strong>{site.name}</strong><small>{site.assets.length} {site.energyType === 'wind' ? 'turbines' : 'assets'} · {site.countryName}</small><span className="site-readiness">{forecastIds(site.assets).length ? 'Forecasting available' : 'Forecasting not connected'}</span></span><Icon name="chevron" size={13} /></button>)}</div>
        {!loading && !assetError && !visibleSites.length && <div className="directory-empty"><Icon name={filter === 'all' ? 'pin' : energyTypes.find(t => t.id === filter)!.icon} size={25} /><strong>No {filter === 'all' ? 'energy' : filter} sites connected</strong><p>{filter === 'hydro' || filter === 'solar' || filter === 'other' ? 'This source is ready for a future asset catalog and forecasting model.' : 'Connected stations will appear here when added to the registry.'}</p></div>}

        {currentSite && <div className="site-detail"><div><span className="section-label">SELECT FORECAST ASSETS</span><span className="subtle-label">{chosenIds.length} selected</span></div>{currentSite.assets.map(asset => {
          const supported = forecastIds([asset]).length > 0;
          return <label key={asset.id} className="explore-asset"><input type="checkbox" disabled={!supported} checked={!!asset.forecast_turbine_id && selected.includes(asset.forecast_turbine_id)} onChange={() => { const id = asset.forecast_turbine_id!; setSelected(ids => ids.includes(id) ? ids.filter(i => i !== id) : [...ids, id]); }} /><span><strong>{asset.name}</strong><small>{asset.latitude != null && asset.longitude != null ? `${asset.latitude.toFixed(4)}°, ${asset.longitude.toFixed(4)}°` : 'Coordinates not configured'}</small></span><span className="asset-capacity">{asset.rated_power_kw != null ? `${asset.rated_power_kw.toLocaleString()} kW` : 'Capacity —'}</span></label>;
        })}<button className="button primary open-forecast" disabled={!chosenIds.length || forecastingDisabled || !!assetError || loading} onClick={() => onOpenForecast(chosenIds)}>Open forecast<Icon name="arrow" size={15} /></button><p className="directory-message">{forecastingDisabled ? 'Forecast service is loading, unavailable, or processing a job.' : 'Choose an issue time and horizon in the forecast workspace.'}</p></div>}
        <div className="directory-foot"><Icon name="info" size={13} /><span>Only connected assets are shown. Hydro, solar, and other sources will use their own forecasting models.</span></div>
      </aside>
    </div>
    <footer className="explore-footer"><span><span className="status-dot good" />ENERGY INFRASTRUCTURE</span><span>Geographic selection · {assets.length} connected assets · UTC forecasts</span></footer>
  </section>;
}
