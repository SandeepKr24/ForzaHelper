-- 01_fix_encoding.sql
-- Repairs 28 rows whose accented characters became U+FFFD during the original import.
-- Replacements were matched unambiguously against "Forza Horizon 6 Car List.xlsx".
-- The corrupted character is matched with LIKE '_' so this file stays valid
-- regardless of the encoding your SQL client pastes it in.
-- Each statement was verified to match exactly one row. Re-running is a no-op.

BEGIN;

UPDATE public.cars SET "Model" = 'R8 Coupé V10 GT RWD'
 WHERE "Year" = 2023 AND "Make" = 'Audi' AND "Model" LIKE 'R8 Coup_ V10 GT RWD';

UPDATE public.cars SET "Model" = 'R8 Coupé V10 Plus 5.2 FSI Quattro'
 WHERE "Year" = 2013 AND "Make" = 'Audi' AND "Model" LIKE 'R8 Coup_ V10 Plus 5.2 FSI Quattro';

UPDATE public.cars SET "Model" = 'RS 5 Coupé'
 WHERE "Year" = 2011 AND "Make" = 'Audi' AND "Model" LIKE 'RS 5 Coup_';

UPDATE public.cars SET "Model" = 'TT RS Coupé'
 WHERE "Year" = 2010 AND "Make" = 'Audi' AND "Model" LIKE 'TT RS Coup_';

UPDATE public.cars SET "Model" = 'M2 Competition Coupé'
 WHERE "Year" = 2020 AND "Make" = 'BMW' AND "Model" LIKE 'M2 Competition Coup_';

UPDATE public.cars SET "Model" = 'M4 Competition Coupé'
 WHERE "Year" = 2021 AND "Make" = 'BMW' AND "Model" LIKE 'M4 Competition Coup_';

UPDATE public.cars SET "Model" = 'M4 Competition Coupé Welcome Pack'
 WHERE "Year" = 2021 AND "Make" = 'BMW' AND "Model" LIKE 'M4 Competition Coup_ Welcome Pack';

UPDATE public.cars SET "Model" = 'M4 Coupé'
 WHERE "Year" = 2014 AND "Make" = 'BMW' AND "Model" LIKE 'M4 Coup_';

UPDATE public.cars SET "Model" = 'M8 Competition Coupé'
 WHERE "Year" = 2020 AND "Make" = 'BMW' AND "Model" LIKE 'M8 Competition Coup_';

UPDATE public.cars SET "Model" = 'Z4 M Coupé'
 WHERE "Year" = 2008 AND "Make" = 'BMW' AND "Model" LIKE 'Z4 M Coup_';

UPDATE public.cars SET "Model" = 'Toyota Tacoma TRD ‘The Performance Truck’'
 WHERE "Year" = 2019 AND "Make" = 'DeBerti' AND "Model" LIKE 'Toyota Tacoma TRD _The Performance Truck_';

UPDATE public.cars SET "Model" = 'Huracán EVO'
 WHERE "Year" = 2020 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Hurac_n EVO';

UPDATE public.cars SET "Model" = 'Huracán EVO Spider'
 WHERE "Year" = 2022 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Hurac_n EVO Spider';

UPDATE public.cars SET "Model" = 'Huracán LP 610-4'
 WHERE "Year" = 2015 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Hurac_n LP 610-4';

UPDATE public.cars SET "Model" = 'Huracán Sterrato'
 WHERE "Year" = 2022 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Hurac_n Sterrato';

UPDATE public.cars SET "Model" = 'Huracán STO'
 WHERE "Year" = 2020 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Hurac_n STO';

UPDATE public.cars SET "Model" = 'Huracán Tecnica'
 WHERE "Year" = 2022 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Hurac_n Tecnica';

UPDATE public.cars SET "Model" = 'Murciélago LP 670-4 SV'
 WHERE "Year" = 2010 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Murci_lago LP 670-4 SV';

UPDATE public.cars SET "Model" = 'Sián Roadster'
 WHERE "Year" = 2020 AND "Make" = 'Lamborghini' AND "Model" LIKE 'Si_n Roadster';

UPDATE public.cars SET "Model" = '12C Coupé'
 WHERE "Year" = 2011 AND "Make" = 'McLaren' AND "Model" LIKE '12C Coup_';

UPDATE public.cars SET "Model" = '570S Coupé'
 WHERE "Year" = 2015 AND "Make" = 'McLaren' AND "Model" LIKE '570S Coup_';

UPDATE public.cars SET "Model" = '600LT Coupé'
 WHERE "Year" = 2018 AND "Make" = 'McLaren' AND "Model" LIKE '600LT Coup_';

UPDATE public.cars SET "Model" = '765LT Coupé'
 WHERE "Year" = 2021 AND "Make" = 'McLaren' AND "Model" LIKE '765LT Coup_';

UPDATE public.cars SET "Model" = 'C 63 S Coupé'
 WHERE "Year" = 2016 AND "Make" = 'Mercedes-AMG' AND "Model" LIKE 'C 63 S Coup_';

UPDATE public.cars SET "Model" = 'GT 4-Door Coupé'
 WHERE "Year" = 2018 AND "Make" = 'Mercedes-AMG' AND "Model" LIKE 'GT 4-Door Coup_';

UPDATE public.cars SET "Model" = '300 SL Coupé'
 WHERE "Year" = 1954 AND "Make" = 'Mercedes-Benz' AND "Model" LIKE '300 SL Coup_';

UPDATE public.cars SET "Model" = 'C 63 AMG Coupé Black Series'
 WHERE "Year" = 2012 AND "Make" = 'Mercedes-Benz' AND "Model" LIKE 'C 63 AMG Coup_ Black Series';

UPDATE public.cars SET "Model" = 'Mégane R26.R'
 WHERE "Year" = 2008 AND "Make" = 'Renault' AND "Model" LIKE 'M_gane R26.R';

-- Verify before committing: expect 0.
SELECT count(*) AS still_corrupted
FROM public.cars
WHERE "Make" LIKE '%' || chr(65533) || '%'
   OR "Model" LIKE '%' || chr(65533) || '%';

COMMIT;
