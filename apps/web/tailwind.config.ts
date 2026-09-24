import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./lib/**/*.{js,ts,jsx,tsx,mdx}"
  ],
  theme: {
    extend: {
      colors: {
        ink: {
          DEFAULT: "#0f172a",
          muted: "#475569",
          subtle: "#64748b",
          faint: "#6a7380"
        },
        paper: {
          DEFAULT: "#fdfcfb",
          elevated: "#ffffff",
          muted: "#f8fafc",
          border: "#e2e8f0"
        },
        action: {
          DEFAULT: "#0f172a",
          hover: "#1e293b",
          soft: "#f1f5f9",
          accent: "#6366f1"
        },
        status: {
          mock: "#f59e0b",
          connected: "#10b981",
          stale: "#f59e0b",
          error: "#ef4444",
          pending: "#6366f1"
        }
      },
      fontFamily: {
        sans: ["var(--font-inter)", "system-ui", "sans-serif"],
        display: ["var(--font-newsreader)", "serif"]
      },
      borderRadius: {
        xl: "1rem",
        "2xl": "1.5rem"
      },
      boxShadow: {
        soft: "0 1px 3px rgba(15,23,42,0.06), 0 8px 24px rgba(15,23,42,0.06)",
        elevated: "0 4px 12px rgba(15,23,42,0.08), 0 16px 48px rgba(15,23,42,0.12)"
      }
    }
  },
  plugins: []
};
export default config;
