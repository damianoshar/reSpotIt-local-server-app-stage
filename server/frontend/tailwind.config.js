/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,jsx}'],
  theme: {
    extend: {
      colors: {
        base:        '#121212',
        panel:       '#181818',
        card:        '#242424',
        elevated:    '#282828',
        border:      '#333333',
        'border-sub':'#242424',
        accent:      '#1DB954',
        'accent-2':  '#1ED760',
        'accent-dim':'#14833b',
        ink:         '#FFFFFF',
        secondary:   '#B3B3B3',
        muted:       '#555555',
        ok:          '#1DB954',
        err:         '#E22134',
      },
      fontFamily: {
        display: ['"Bodoni Moda"', 'Georgia', 'serif'],
        body:    ['"Outfit"', 'system-ui', 'sans-serif'],
        mono:    ['"Space Mono"', 'monospace'],
      },
      animation: {
        'fade-in':    'fadeIn 0.4s ease forwards',
        'slide-down': 'slideDown 0.35s ease forwards',
        'pulse-soft': 'pulseSoft 2s ease-in-out infinite',
        'shimmer':    'shimmer 1.6s ease-in-out infinite',
      },
      keyframes: {
        fadeIn:    { from: { opacity: 0 }, to: { opacity: 1 } },
        slideDown: { from: { opacity: 0, transform: 'translateY(-12px)' }, to: { opacity: 1, transform: 'translateY(0)' } },
        pulseSoft: { '0%,100%': { opacity: 1 }, '50%': { opacity: 0.5 } },
        shimmer:   {
          '0%':   { backgroundPosition: '-400px 0' },
          '100%': { backgroundPosition: '400px 0' },
        },
      },
    },
  },
  plugins: [],
}
