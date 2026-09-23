import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { expect, it, vi } from 'vitest';
import { api } from '../../src/api';
import DataWorkspace from '../../src/components/DataWorkspace';

vi.mock('../../src/api', () => ({ api: { fetchWeather: vi.fn(), weather: vi.fn() } }));

it('fetches weather for the displayed configured turbine on first render and after configuration changes', async () => {
  vi.mocked(api.weather).mockResolvedValue([]);
  vi.mocked(api.fetchWeather).mockResolvedValue({ id: 'candidate' } as never);
  const props = { datasets: [], disabled: false, onChanged: vi.fn().mockResolvedValue(undefined) };
  const { rerender } = render(<DataWorkspace {...props} turbines={[{ id: 'custom-a', name: 'Custom A' }]} />);
  const summary = screen.getByText('Weather archive');
  summary.closest('details')!.open = true;
  fireEvent.click(screen.getByRole('button', { name: 'Fetch candidate' }));
  await waitFor(() => expect(api.fetchWeather).toHaveBeenCalledWith(expect.objectContaining({ turbine_id: 'custom-a' })));
  await waitFor(() => expect((screen.getByRole('button', { name: 'Fetch candidate' }) as HTMLButtonElement).disabled).toBe(false));
  rerender(<DataWorkspace {...props} turbines={[{ id: 'custom-b', name: 'Custom B' }]} />);
  fireEvent.click(screen.getByRole('button', { name: 'Fetch candidate' }));
  await waitFor(() => expect(api.fetchWeather).toHaveBeenLastCalledWith(expect.objectContaining({ turbine_id: 'custom-b' })));
});
