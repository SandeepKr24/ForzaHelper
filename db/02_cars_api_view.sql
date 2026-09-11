-- 02_cars_api_view.sql
-- Additive only: creates a view. Does NOT alter public.cars.
--
-- Gives the backend snake_case names, a real integer price, a stable text id,
-- and the derived power-to-weight figure from doc section 7, so no application
-- code has to quote "Value (Cr)" or parse comma-grouped strings.
--
-- Run 01_fix_encoding.sql first, otherwise ids for the 28 affected rows change later.

CREATE OR REPLACE VIEW public.cars_api AS
SELECT
    -- Stable, reproducible id derived from the natural key. Verified unique.
    regexp_replace(
        lower("Make" || '-' || "Model" || '-' || "Year"),
        '[^a-z0-9]+', '-', 'g'
    )                                              AS id,

    "Year"                                         AS year,
    "Make"                                         AS make,
    "Model"                                        AS model,
    "Make" || ' ' || "Model"                       AS full_name,
    "Country"                                      AS country,
    "Type"                                         AS car_type,

    -- "2,50,000" -> 250000. Indian digit grouping, so strip every comma.
    NULLIF(regexp_replace("Value (Cr)", ',', '', 'g'), '')::bigint
                                                   AS price_cr,
    "Rarity"                                       AS rarity,
    string_to_array("Source", ', ')                AS acquisition_methods,

    "Class"                                        AS pi_class,
    "PI"                                           AS pi,
    "Power (HP)"                                   AS horsepower,
    "Torque (Imperial)"                            AS torque_lbft,
    "Torque (Metric)"                              AS torque_nm,
    "Weight (Imperial)"                            AS weight_lb,
    "Weight (Metric)"                              AS weight_kg,
    "Drivetrain"                                   AS drivetrain,

    -- hp per metric tonne (doc section 7). NULL-safe: NULLIF guards divide-by-zero.
    round(
        ("Power (HP)"::numeric / NULLIF("Weight (Imperial)"::numeric / 2204.62, 0)),
        2
    )                                              AS hp_per_tonne,

    round(
        (NULLIF(regexp_replace("Value (Cr)", ',', '', 'g'), '')::numeric
         / NULLIF("Power (HP)", 0)),
        2
    )                                              AS price_per_hp
FROM public.cars;

COMMENT ON VIEW public.cars_api IS
    'Query-friendly projection of public.cars: snake_case, integer price_cr, stable id, derived metrics.';
