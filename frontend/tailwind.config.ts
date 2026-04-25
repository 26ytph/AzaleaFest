import type { Config } from 'tailwindcss'

const config: Config = {
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        brand: {
          place: '#3B82F6',
          rec: '#F59E0B',
          legal: '#10B981',
          illegal: '#EF4444',
          unknown: '#9CA3AF',
        },
      },
      keyframes: {
        pulse_ring: {
          '0%': { transform: 'scale(0.9)', opacity: '0.7' },
          '70%': { transform: 'scale(1.6)', opacity: '0' },
          '100%': { transform: 'scale(1.6)', opacity: '0' },
        },
      },
      animation: {
        'pulse-ring': 'pulse_ring 1.6s ease-out infinite',
      },
    },
  },
  plugins: [],
}

export default config
