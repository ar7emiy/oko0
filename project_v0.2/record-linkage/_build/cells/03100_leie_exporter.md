## LEIE exporter

Raw OIG LEIE (`UPDATED.csv`, 84,001 rows) → the input schema. The export keeps DOB and the
street address, so it lives only in gitignored `data/` (it is personal data about real
people). Mapping, as decided in PLAN.md open question 3:

| LEIE | Input column |
|---|---|
| LASTNAME, FIRSTNAME, MIDNAME | last_name, first_name, middle_name |
| BUSNAME | business_name |
| GENERAL | professional_license_type (drives the inferred category) |
| SPECIALTY | provider_specialty |
| NPI (all zeros = none) | provider_npi for a person, clinic_npi for a business |
| DOB (YYYYMMDD) | dob (ISO) |
| ADDRESS | street_number, street_direction, street_name, street_type, unit (parsed) |
| CITY, STATE, ZIP | city, state, zip |
| EXCLTYPE, EXCLDATE, REINDATE, WAIVERDATE, WVRSTATE, UPIN | x_ display columns, never compared |

`record_id` is goko's scheme (a hash of the record's identifying fields), so it is stable
across refreshes.

**Where Splink would do better.** Not applicable: this is data preparation.