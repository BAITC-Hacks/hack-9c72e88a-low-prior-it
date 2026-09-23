import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import test from 'node:test';
import { countryAltitude, forecastIds, groupSites } from '../src/explore/catalog.ts';

const wind = (id, extra = {}) => ({
  id, name: id, energy_type: 'wind', country_code: 'KZ', country_name: 'Kazakhstan',
  site_id: 'site-1', site_name: 'Wind farm', latitude: 43.64, longitude: 78.53,
  rated_power_kw: null, forecast_supported: true, forecast_turbine_id: id, ...extra,
});

test('nearby turbines group only when their registry explicitly shares a site', () => {
  assert.equal(groupSites([wind('one'), wind('two')]).length, 1);
  assert.equal(groupSites([wind('one', { site_id: null }), wind('two', { site_id: null })]).length, 2);
});

test('country and energy type remain separate even with a reused site identifier', () => {
  const sites = groupSites([wind('one'), wind('two', { country_code: 'US' }), wind('solar', { energy_type: 'solar', forecast_supported: false, forecast_turbine_id: null })]);
  assert.equal(sites.length, 3);
  assert.deepEqual(sites.map(s => s.assets.length), [1, 1, 1]);
});

test('unlocated assets remain in the directory without invented map coordinates', () => {
  const [site] = groupSites([wind('unknown', { latitude: null, longitude: null })]);
  assert.equal(site.lat, null);
  assert.equal(site.lng, null);
  assert.equal(site.assets.length, 1);
  const [mixed] = groupSites([wind('known'), wind('unknown', { latitude: null, longitude: null })]);
  assert.equal(mixed.lat, 43.64);
  assert.ok(Math.abs(mixed.lng - 78.53) < 1e-8);
});

test('a site crossing the dateline stays near the dateline', () => {
  const [site] = groupSites([wind('one', { longitude: 179 }), wind('two', { longitude: -179 })]);
  assert.ok(Math.abs(Math.abs(site.lng) - 180) < 1e-8);
});

test('forecast handoff admits only explicitly supported wind turbine mappings', () => {
  assert.deepEqual(forecastIds([
    wind('one'), wind('duplicate', { forecast_turbine_id: 'one' }),
    wind('unsupported', { forecast_supported: false }),
    wind('unmapped', { forecast_turbine_id: null }),
    wind('hydro', { energy_type: 'hydro' }),
  ]), ['one']);
});

test('narrow country framing zooms out and extreme extents stay bounded', () => {
  assert.ok(countryAltitude(30, .6) > countryAltitude(30, 1.5));
  assert.ok(countryAltitude(1, 1) > 0);
  assert.ok(countryAltitude(170, .1) <= 2.5);
});

test('bundled boundaries cover configured asset countries with usable geometry', () => {
  const map = JSON.parse(readFileSync(new URL('../public/geo/countries.geojson', import.meta.url), 'utf8'));
  const turbines = JSON.parse(readFileSync(new URL('../../config/turbines.example.json', import.meta.url), 'utf8'));
  assert.equal(map.type, 'FeatureCollection');
  assert.equal(new Set(map.features.map(f => f.properties.code)).size, map.features.length);
  for (const turbine of turbines) {
    const feature = map.features.find(f => f.properties.code === turbine.country_code);
    assert.ok(feature, `Missing boundaries for ${turbine.country_code}`);
    assert.ok(feature.geometry.coordinates.length);
    assert.ok(Number.isFinite(feature.properties.lat) && Number.isFinite(feature.properties.lng));
    assert.ok(feature.properties.span > 0);
  }
});
