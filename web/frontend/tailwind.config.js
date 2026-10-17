import colors from "tailwindcss/colors";

/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      colors: {
        // 品牌色：粉色；中性色统一用 zinc（925：深色模式下侧栏的底色）
        brand: colors.pink,
        zinc: { 925: "#111113" },
      },
      fontFamily: {
        sans: [
          "-apple-system", "BlinkMacSystemFont", '"Segoe UI"', '"PingFang SC"', '"Hiragino Sans GB"',
          '"Microsoft YaHei"', "Roboto", '"Helvetica Neue"', "Arial", "sans-serif",
        ],
        mono: ['"SF Mono"', "ui-monospace", "Menlo", "Monaco", "Consolas", "monospace"],
      },
      boxShadow: {
        soft: "0 1px 2px rgb(0 0 0 / 0.04), 0 6px 24px -6px rgb(0 0 0 / 0.08)",
        pop: "0 12px 40px -8px rgb(0 0 0 / 0.25)",
      },
      keyframes: {
        "fade-in": { from: { opacity: "0" }, to: { opacity: "1" } },
        "pop-in": {
          from: { opacity: "0", transform: "translateY(4px) scale(0.98)" },
          to: { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        "slide-up": { from: { opacity: "0", transform: "translateY(8px)" }, to: { opacity: "1", transform: "translateY(0)" } },
        shimmer: { from: { backgroundPosition: "200% 0" }, to: { backgroundPosition: "-200% 0" } },
        blink: { "0%, 100%": { opacity: "1" }, "50%": { opacity: "0" } },
      },
      animation: {
        "fade-in": "fade-in 150ms ease-out",
        "pop-in": "pop-in 160ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        "slide-up": "slide-up 220ms cubic-bezier(0.2, 0.8, 0.2, 1)",
        shimmer: "shimmer 1.6s linear infinite",
        blink: "blink 1s step-end infinite",
      },
    },
  },
  plugins: [],
};
