// ForzaHelper frontend configuration.
//
// The browser talks only to the ForzaHelper backend. It holds no database
// credentials and never sends SQL: it posts structured filters and receives
// structured rows.
window.FH6_CONFIG = {
  // Local development. Point this at the deployed backend in production.
  apiBaseUrl: "http://localhost:8000"
};
