# Forza Helper — FH6 Car Database

Static site. No build step, no framework, no server.

## Files
- `index.html` — the whole app
- `support.js` — runtime it loads
- `config.js` — your Supabase URL, anon key, table and RPC name
- `vercel.json` — clean URLs; `config.js` served `no-store` so credential edits take effect immediately

## Deploy
1. Put your values in `config.js`.
2. From this folder: `vercel deploy --prod` — or drag the folder onto vercel.com/new.
   Framework preset: **Other**. Build command: none. Output directory: `./`.

## Backend contract
The app sends one POST per view:

    POST {supabaseUrl}/rest/v1/rpc/{sqlRpc}
    { "query": "SELECT ..." }

The function must accept a single `query` text argument and return rows as JSON.
Make it `SECURITY INVOKER`, read-only, and reject anything that is not a `SELECT`.

Expected columns on the table: Year, Make, Model, Type, Class, PI, Country,
Value (Cr), Rarity, Power (HP), Torque (Imperial), Torque (Metric),
Weight (Imperial), Weight (Metric), Drivetrain, Engine Pos.,
Power to Weight (Imperial), Power to Weight (Metric), Source.
