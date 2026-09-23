import type { EnergyAsset } from '../api';
import type { IconName } from '../components/Icon';

export type EnergyType = EnergyAsset['energy_type'];
export type EnergyFilter = 'all' | EnergyType;
export const energyTypes: { id: EnergyType; name: string; icon: IconName; description: string }[] = [
  { id: 'wind', name: 'Wind', icon: 'turbine', description: 'Wind turbines & farms' },
  { id: 'hydro', name: 'Hydro', icon: 'water', description: 'Hydroelectric stations' },
  { id: 'solar', name: 'Solar', icon: 'sun', description: 'Solar generation sites' },
  { id: 'other', name: 'Other', icon: 'layers', description: 'Additional energy sources' },
];

export type Country = {
  type: 'Feature';
  properties: { code: string; name: string; lat: number; lng: number; span: number };
  geometry: { type: string; coordinates: unknown[] };
};

export type AssetSite = {
  id: string;
  name: string;
  countryCode: string | null;
  countryName: string;
  energyType: EnergyType;
  lat: number | null;
  lng: number | null;
  assets: EnergyAsset[];
};

export function hasCoordinates(asset: EnergyAsset): boolean {
  return asset.latitude != null && asset.longitude != null && Number.isFinite(asset.latitude) && Number.isFinite(asset.longitude);
}

export function groupSites(assets: EnergyAsset[]): AssetSite[] {
  const groups = new Map<string, EnergyAsset[]>();
  for (const asset of assets) {
    // Site grouping is explicit registry metadata; proximity never invents a farm.
    const key = `${asset.country_code || 'unknown'}:${asset.energy_type}:${asset.site_id || asset.id}`;
    groups.set(key, [...(groups.get(key) || []), asset]);
  }
  return [...groups].map(([id, members]) => {
    const first = members[0];
    const located = members.filter(hasCoordinates);
    const lngX = located.reduce((sum, asset) => sum + Math.cos(asset.longitude! * Math.PI / 180), 0);
    const lngY = located.reduce((sum, asset) => sum + Math.sin(asset.longitude! * Math.PI / 180), 0);
    return {
      id, name: first.site_name || first.name, countryCode: first.country_code || null,
      countryName: first.country_name || first.country_code || 'Country not assigned', energyType: first.energy_type,
      lat: located.length ? located.reduce((sum, asset) => sum + asset.latitude!, 0) / located.length : null,
      lng: located.length ? Math.atan2(lngY, lngX) * 180 / Math.PI : null,
      assets: members,
    };
  }).sort((a, b) => a.name.localeCompare(b.name));
}

export function forecastIds(assets: EnergyAsset[]): string[] {
  return [...new Set(assets.filter(asset => asset.energy_type === 'wind' && asset.forecast_supported && asset.forecast_turbine_id)
    .map(asset => asset.forecast_turbine_id!))];
}

export function countryAltitude(span: number, aspect: number): number {
  // Fit the main landmass, allowing extra space on narrow screens.
  return Math.min(2.5, Math.max(.38, (span / 65) * Math.max(1, 1 / Math.max(.35, aspect))));
}
