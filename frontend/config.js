// Centralized frontend runtime config.
// Local development uses localhost.
// For deployment, set API_BASE_URL to your backend domain.
window.APP_CONFIG = {
  API_BASE_URL: window.location.hostname === "localhost" || window.location.hostname === "127.0.0.1"
    ? "http://127.0.0.1:8000"
    : `${window.location.protocol}//api.${window.location.hostname}`
};
