// Supabase connection for the FH6 Car Database.
// The anon key is public by design — protect data with RLS and a read-only SQL function.
window.FH6_CONFIG = {
  supabaseUrl: "https://YOUR-PROJECT.supabase.co",
  supabaseAnonKey: "YOUR-ANON-KEY",
  table: "cars",
  sqlRpc: "run_car_query"
};
