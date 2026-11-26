/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        debunk: {
          bg: '#0f1117',
          surface: '#1a1d27',
          border: '#2d3148',
          accent: '#7c3aed',
          'accent-hover': '#6d28d9',
          success: '#10b981',
          error: '#ef4444',
          warning: '#f59e0b',
          text: '#e2e8f0',
          muted: '#8892a4',
        },
      },
      fontFamily: {
        mono: ['JetBrains Mono', 'Fira Code', 'Consolas', 'monospace'],
      },
      animation: {
        'pulse-fast': 'pulse 1s cubic-bezier(0.4, 0, 0.6, 1) infinite',
      },
    },
  },
  plugins: [],
};
