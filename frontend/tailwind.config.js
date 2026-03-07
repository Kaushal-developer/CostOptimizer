/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  darkMode: 'class',
  theme: {
    extend: {
      colors: {
        brand: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
        },
        sidebar: {
          DEFAULT: '#0b0e1a',
          hover: '#161b2e',
        },
        surface: {
          DEFAULT: '#0f1117',
          50: '#1a1d2e',
          100: '#1e2235',
          200: '#252a3a',
          300: '#2d3348',
        },
        accent: {
          cyan: '#06b6d4',
          emerald: '#10b981',
          amber: '#f59e0b',
          rose: '#f43f5e',
          violet: '#8b5cf6',
        },
      },
      boxShadow: {
        glow: '0 0 20px rgba(99, 102, 241, 0.15)',
      },
    },
  },
  plugins: [],
};
