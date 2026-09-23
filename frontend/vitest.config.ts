import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    include: ['tests/flow/**/*.test.ts', 'tests/flow/**/*.test.tsx'],
    setupFiles: ['./tests/flow/setup.ts'],
    restoreMocks: true,
  },
});
