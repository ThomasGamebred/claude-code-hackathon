/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      colors: {
        swamp: {
          50: "#f3f7f5",
          100: "#dee9e3",
          200: "#bcd2c7",
          300: "#94b5a5",
          400: "#6f9683",
          500: "#547b69",
          600: "#406253",
          700: "#344e43",
          800: "#2b3e37",
          900: "#1f2d28",
        },
        gold: {
          50: "#fdf9ec",
          100: "#faf0c8",
          200: "#f5e08c",
          300: "#eecb52",
          400: "#e6b62c",
          500: "#cc991e",
          600: "#a87618",
          700: "#855817",
          800: "#6e4719",
          900: "#5d3c1a",
        },
      },
      boxShadow: {
        card: "0 1px 2px rgba(15, 23, 42, 0.04), 0 4px 12px rgba(15, 23, 42, 0.06)",
      },
    },
  },
  plugins: [],
};
