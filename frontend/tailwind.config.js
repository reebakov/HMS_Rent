/** @type {import('tailwindcss').Config} */
const color = (name) => `hsl(var(--${name}) / <alpha-value>)`

export default {
  darkMode: 'class',
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"Inter Variable"', 'Inter', 'system-ui', 'sans-serif'],
      },
      colors: {
        background: color('background'),
        foreground: color('foreground'),
        card: color('card'),
        muted: { DEFAULT: color('muted'), foreground: color('muted-foreground') },
        border: color('border'),
        ring: color('ring'),
        primary: { DEFAULT: color('primary'), foreground: color('primary-foreground') },
        success: color('success'),
        warning: color('warning'),
        danger: color('danger'),
        sidebar: { DEFAULT: color('sidebar'), foreground: color('sidebar-foreground'), muted: color('sidebar-muted') },
      },
      borderRadius: { xl: '0.875rem', '2xl': '1.125rem' },
      boxShadow: {
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
        lift: '0 10px 30px -12px rgb(15 23 42 / 0.25)',
      },
      keyframes: {
        'fade-in': { from: { opacity: 0 }, to: { opacity: 1 } },
        'zoom-in': { from: { opacity: 0, transform: 'translate(-50%, -48%) scale(0.97)' }, to: { opacity: 1, transform: 'translate(-50%, -50%) scale(1)' } },
        'slide-in': { from: { transform: 'translateX(100%)' }, to: { transform: 'translateX(0)' } },
      },
      animation: {
        'fade-in': 'fade-in 150ms ease-out',
        'zoom-in': 'zoom-in 180ms cubic-bezier(0.16, 1, 0.3, 1)',
        'slide-in': 'slide-in 250ms cubic-bezier(0.16, 1, 0.3, 1)',
      },
    },
  },
  plugins: [],
}
