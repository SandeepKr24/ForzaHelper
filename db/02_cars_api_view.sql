-- 02_cars_api_view.sql
-- additive only: creates a view. Does NOT alter public.cars.
--
-- gives the backend snake_case names, integer price, stable text id,
-- and the derived power-to-weight figures. 
--
-- run 01_fix_encoding.sql first to repair the 28 rows whose accented characters became U+FFFD during the original import.

CREATE OR REPLACE VIEW public.cars_api AS
SELECT
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
    'Query-friendly projection of public.cars: snake_case, integer price_cr, stable id, derived metrics.';
