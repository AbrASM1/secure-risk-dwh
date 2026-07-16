# lei_gleif_sample.csv

| Item | Value |
|---|---|
| Content | 1,000 Legal Entity Identifier codes, codes only, sorted |
| Origin | GLEIF LEI records API, `https://api.gleif.org/api/v1/lei-records` |
| Query | for each legal-address country CH, DE, ES, FR, GB, IT, JP, LU, NL, US: `page[size]=100`, `page[number]=1`, `sort=lei`, `filter[entity.legalAddress.country]=<country>`; only `attributes.lei` kept |
| Extraction date | 2026-11-03 |
| Licence | GLEIF data, CC0 1.0 |
| Use | oracle for the simulator LEI check and rule C06 (SPEC §11) |
