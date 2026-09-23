export const forecastSections = ['forecast', 'stations', 'activity', 'hourly', 'replay', 'data'] as const;
export type WorkspaceSection = 'explore' | typeof forecastSections[number];
export type WorkspaceView = 'explore' | 'forecast';

export function sectionFromHash(hash: string): WorkspaceSection | null {
  const value = hash.replace(/^#/, '');
  return value === 'explore' || forecastSections.some(section => section === value) ? value as WorkspaceSection : null;
}

export function initialSection(hash: string, savedView: string | null): WorkspaceSection {
  return sectionFromHash(hash) || (!hash && savedView === 'forecast' ? 'forecast' : 'explore');
}

export function workspaceForSection(section: WorkspaceSection): WorkspaceView {
  return section === 'explore' ? 'explore' : 'forecast';
}
