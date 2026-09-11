-- 03_optional_unaccent_ids.sql  (OPTIONAL)
--
-- Without this, accented characters collapse to a hyphen in the generated id:
--     lamborghini-hurac-n-evo-2020
-- With it:
--     lamborghini-huracan-evo-2020
--
-- Verified on the live data: still 635 distinct ids for 635 rows.
--
-- Decide before any id is stored elsewhere or shipped in a URL, because running
-- this later changes the id of every accented car (31 rows) -- a breaking change.
-- Nothing currently consumes these ids, so right now it is free to apply.

CREATE EXTENSION IF NOT EXISTS unaccent WITH SCHEMA extensions;

CREATE OR REPLACE VIEW public.cars_api AS
SELECT
    regexp_replace(
        lower(extensions.unaccent("Make" || '-' || "Model" || '-' || "Year")),
        '[^a-z0-9]+', '-', 'g'
    )                                              AS id,

    "Year"                                         AS year,
    "Make"                                         AS make,
    "Model"                                        AS model,
    "Make" || ' ' || "Model"                       AS full_name,
    "Country"                                      AS country,
    "Type"                                         AS car_type,

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
    'Query-friendly projection of public.cars: snake_case, integer price_cr, stable unaccented id, derived metrics.';
