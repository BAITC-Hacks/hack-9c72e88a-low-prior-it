import { fireEvent, render, screen } from '@testing-library/react';
import { expect, it } from 'vitest';
import ProfileMenu from '../../src/components/ProfileMenu';
import { initializeTheme } from '../../src/theme';

it('changes and remembers appearance, then restores trigger focus on Escape', () => {
  initializeTheme();
  render(<ProfileMenu />);
  const trigger = screen.getByRole('button', { name: 'Profile and appearance' });
  fireEvent.click(trigger);
  fireEvent.click(screen.getByRole('radio', { name: /Light/ }));
  expect(document.documentElement.dataset.theme).toBe('light');
  expect(localStorage.getItem('low-prior-theme')).toBe('light');
  fireEvent.click(screen.getByRole('radio', { name: /Black/ }));
  expect(document.documentElement.dataset.theme).toBe('black');
  fireEvent.keyDown(document, { key: 'Escape' });
  expect(screen.queryByRole('dialog')).toBeNull();
  expect(document.activeElement).toBe(trigger);
});
