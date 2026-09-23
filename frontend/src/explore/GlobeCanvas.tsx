import { useEffect, useMemo, useRef, useState } from 'react';
import Globe, { type GlobeMethods } from 'react-globe.gl';
import { MeshPhongMaterial } from 'three';
import { useTheme } from '../theme';
import { countryAltitude, type AssetSite, type Country } from './catalog';

type Props = {
  countries: Country[];
  country: Country | null;
  sites: AssetSite[];
  site: AssetSite | null;
  active: boolean;
  rotating: boolean;
  reducedMotion: boolean;
  resetKey: number;
  onCountry: (country: Country) => void;
  onSite: (site: AssetSite) => void;
  onInteraction: () => void;
  onReady: () => void;
  onUnavailable: () => void;
};

function tooltip(text: string) {
  const node = document.createElement('div');
  node.className = 'globe-tooltip';
  node.textContent = text;
  return node.outerHTML;
}

export default function GlobeCanvas({ countries, country, sites, site, active, rotating, reducedMotion, resetKey, onCountry, onSite, onInteraction, onReady, onUnavailable }: Props) {
  const globe = useRef<GlobeMethods | undefined>(undefined);
  const host = useRef<HTMLDivElement>(null);
  const [size, setSize] = useState({ width: 600, height: 580 });
  const [ready, setReady] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const { theme } = useTheme();
  const palette = useMemo(() => {
    const style = getComputedStyle(document.documentElement);
    return Object.fromEntries(['ocean', 'land', 'border', 'selected', 'hover'].map(key => [key, style.getPropertyValue(`--globe-${key}`).trim()]));
  }, [theme]);
  const accent = theme === 'light' ? '#007d6b' : '#2de2c5';
  const material = useMemo(() => new MeshPhongMaterial({ color: palette.ocean, shininess: 3 }), [palette.ocean]);
  useEffect(() => () => material.dispose(), [material]);

  useEffect(() => {
    if (!host.current) return;
    const observer = new ResizeObserver(entries => {
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) setSize({ width: Math.round(width), height: Math.round(height) });
    });
    observer.observe(host.current);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!ready || !globe.current) return;
    const g = globe.current;
    const controls = g.controls();
    controls.autoRotateSpeed = .22;
    controls.enablePan = false;
    controls.minDistance = g.getGlobeRadius() * 1.16;
    controls.maxDistance = g.getGlobeRadius() * 4.5;
    const interact = () => { g.pointOfView(g.pointOfView(), 0); onInteraction(); };
    controls.addEventListener('start', interact);
    g.renderer().setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.75));
    const canvas = g.renderer().domElement;
    const lost = (event: Event) => { event.preventDefault(); onUnavailable(); };
    canvas.addEventListener('webglcontextlost', lost);
    return () => { controls.removeEventListener('start', interact); canvas.removeEventListener('webglcontextlost', lost); };
  }, [ready, onInteraction, onUnavailable]);

  useEffect(() => {
    if (!ready || !globe.current) return;
    const g = globe.current;
    const update = () => {
      const visible = active && document.visibilityState !== 'hidden';
      g.controls().autoRotate = visible && rotating && !country && !reducedMotion;
      if (visible) g.resumeAnimation(); else g.pauseAnimation();
    };
    update();
    document.addEventListener('visibilitychange', update);
    return () => { document.removeEventListener('visibilitychange', update); g.pauseAnimation(); };
  }, [ready, active, rotating, country, reducedMotion]);

  useEffect(() => {
    if (!ready || !globe.current || !active) return;
    const target = site?.lat != null && site.lng != null ? { lat: site.lat, lng: site.lng, altitude: .26 }
      : country ? { lat: country.properties.lat, lng: country.properties.lng, altitude: countryAltitude(country.properties.span, size.width / size.height) }
        : { lat: 28, lng: 65, altitude: 2.05 };
    globe.current.pointOfView(target, reducedMotion ? 0 : 1250);
    // Resize changes the viewport without undoing the user's manual camera position.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, active, country?.properties.code, site?.id, reducedMotion, resetKey]);

  const plotted = useMemo(() => sites.filter(s => s.lat != null && s.lng != null), [sites]);
  return <div ref={host} className="globe-canvas" role="img" aria-label="Interactive Earth. Use the country selector and station list for keyboard navigation.">
    <Globe ref={globe} width={size.width} height={size.height} animateIn={false}
      backgroundColor="rgba(0,0,0,0)" globeMaterial={material} showAtmosphere={false} showGraticules={false}
      onGlobeReady={() => { setReady(true); onReady(); }}
      polygonsData={countries} polygonAltitude={.003} polygonSideColor={() => palette.land}
      polygonCapColor={value => {
        const code = (value as Country).properties.code;
        return code === country?.properties.code ? palette.selected : code === hovered ? palette.hover : palette.land;
      }}
      polygonStrokeColor={value => (value as Country).properties.code === country?.properties.code ? accent : palette.border}
      polygonLabel={value => tooltip((value as Country).properties.name)}
      polygonsTransitionDuration={reducedMotion ? 0 : 180}
      onPolygonHover={value => setHovered(value ? (value as Country).properties.code : null)}
      onPolygonClick={value => onCountry(value as Country)}
      pointsData={plotted} pointLat="lat" pointLng="lng" pointAltitude={.012}
      pointRadius={site ? .055 : country ? .18 : .35} pointColor={() => accent} pointResolution={12}
      pointsTransitionDuration={reducedMotion ? 0 : 180}
      pointLabel={value => tooltip(`${(value as AssetSite).name} · ${(value as AssetSite).assets.length} assets`)}
      onPointClick={value => onSite(value as AssetSite)}
    />
  </div>;
}
