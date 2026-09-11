// ForzaHelper frontend configuration.
//
// The browser talks only to the ForzaHelper API. It holds no database
// credentials and never sends SQL: it posts structured filters and receives
// structured rows.
//
// Leave apiBaseUrl empty to use the same origin. On Vercel the API is deployed
// alongside this page at /api, so same-origin is correct and no CORS is needed.
// Set it only to point at a backend on a different host.
window.FH6_CONFIG = {
  apiBaseUrl: ""
};
