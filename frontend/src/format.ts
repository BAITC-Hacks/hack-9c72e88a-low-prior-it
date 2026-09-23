export const seriesColors = ['var(--series-1)', 'var(--series-2)', 'var(--series-3)', 'var(--series-4)'];
export const isActive = (status?: string) => status === 'queued' || status === 'running';
export const utcDate = (value: string) => new Date(value).toLocaleDateString('en-GB', {
  timeZone: 'UTC', day: '2-digit', month: 'short',
});
export const utcClock = (value: string) => new Date(value).toLocaleTimeString('en-GB', {
  timeZone: 'UTC', hour: '2-digit', minute: '2-digit',
});
export const utcTime = (value: string) => `${utcDate(value)}, ${utcClock(value)}`;
export const leadTime = (issuedAt: string, lead: number) =>
  new Date(new Date(issuedAt).getTime() + lead * 3_600_000).toISOString();
export const compassPoint = (degrees: number) =>
  ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'][Math.round(degrees / 45) % 8];
