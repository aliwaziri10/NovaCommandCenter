/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        nova: {
          950: '#0a0f1a',
          900: '#111827',
          800: '#1e293b',
          700: '#334155',
          accent: '#06b6d4',
          success: '#10b981',
        },
      },
    },
  },
  plugins: [],
}
