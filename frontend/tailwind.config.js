/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        pilot: {
          bg: "#0d1117",
          panel: "#161b22",
          accent: "#58a6ff",
          danger: "#f85149",
          ok: "#3fb950",
        },
      },
    },
  },
  plugins: [],
};
