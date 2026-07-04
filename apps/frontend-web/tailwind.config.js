/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: ["var(--font-sans)"],
        display: ["var(--font-display)"],
        mono: ["var(--font-mono)"],
        market: ["var(--font-market)"],
      },
      colors: {
        "finance-bg-root": "var(--color-bg-root)",
        "finance-bg-surface": "var(--color-bg-surface)",
        "finance-bg-card": "var(--color-bg-card)",
        "finance-bg-hover": "var(--color-bg-hover)",
        "finance-border": "var(--color-border)",
        "finance-border-subtle": "var(--color-border-subtle)",
        "finance-text-primary": "var(--color-text-primary)",
        "finance-text-secondary": "var(--color-text-secondary)",
        "finance-text-tertiary": "var(--color-text-tertiary)",
        "finance-text-muted": "var(--color-text-muted)",
        "finance-accent": "var(--color-accent)",
        "finance-accent-soft": "var(--color-accent-soft)",
        "finance-cyan": "var(--color-cyan)",
        "finance-purple": "var(--color-purple)",
        "finance-bullish": "var(--color-bullish)",
        "finance-bearish": "var(--color-bearish)",
        "finance-warning": "var(--color-warning)",
      },
    },
  },
  plugins: [],
};
