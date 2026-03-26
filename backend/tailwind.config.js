// frontend/tailwind.config.js

module.exports = {
  content: [
    "./backend/app/templates/**/*.html",  // To include all templates from backend
    "./frontend/**/*.html",              // If you have frontend HTML
    "./backend/app/static/**/*.css",     // For the CSS inside the static folder
  ],
  theme: {
    extend: {},
  },
  plugins: [],
};
