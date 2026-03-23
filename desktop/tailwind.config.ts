import type { Config } from "tailwindcss";

export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        obsidian: "rgb(var(--color-obsidian) / <alpha-value>)",
        "obsidian-soft": "rgb(var(--color-obsidian-soft) / <alpha-value>)",
        "panel-bg": "rgb(var(--color-panel-bg) / <alpha-value>)",
        "panel-border": "rgb(var(--color-panel-border) / <alpha-value>)",
        "neon-green": "rgb(var(--color-neon-green) / <alpha-value>)",
        "neon-green-soft": "rgb(var(--color-neon-green-soft) / <alpha-value>)",
        "text-main": "rgb(var(--color-text-main) / <alpha-value>)",
        "text-muted": "rgb(var(--color-text-muted) / <alpha-value>)"
      },
      boxShadow: {
        glow:
          "0 0 0 1px rgb(var(--color-neon-green) / var(--theme-glow-ring-opacity)), 0 0 16px rgb(var(--color-neon-green) / var(--theme-glow-blur-opacity))",
        insetGlow: "inset 0 1px 0 rgba(255,255,255,0.03), inset 0 0 0 1px rgb(var(--color-neon-green) / 0.18)",
        card: "var(--theme-card-shadow)"
      },
      borderRadius: {
        xl2: "1.05rem"
      },
      backgroundImage: {
        "noise-grid":
          "radial-gradient(circle at 1px 1px, rgb(var(--color-neon-green) / var(--theme-grid-dot-opacity)) 1px, transparent 0)"
      }
    }
  },
  plugins: []
} satisfies Config;
