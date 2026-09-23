export const forecastSections = ['forecast', 'stations', 'activity', 'hourly', 'replay', 'data', 'insights'] as const;
export type WorkspaceSection = 'explore' | 'evidence' | typeof forecastSections[number];
export type WorkspaceView = 'explore' | 'forecast' | 'evidence';

export function sectionFromHash(hash: string): WorkspaceSection | null {
  const value = hash.replace(/^#/, '');
  return value === 'explore' || value === 'evidence' || forecastSections.some(section => section === value) ? value as WorkspaceSection : null;
}

export function initialSection(hash: string, savedView: string | null): WorkspaceSection {
  return sectionFromHash(hash) || (!hash && (savedView === 'forecast' || savedView === 'evidence') ? savedView : 'explore');
}

export function workspaceForSection(section: WorkspaceSection): WorkspaceView {
  return section === 'explore' || section === 'evidence' ? section : 'forecast';
}
