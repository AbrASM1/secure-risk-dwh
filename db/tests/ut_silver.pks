ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_silver AUTHID DEFINER AS
    --%suite(pkg_silver rules, rejects and silver replacement)

    --%beforeall
    PROCEDURE setup;

    --%test(C01: cpty_id of 20 characters accepted, 21 rejected, blank rejected; cpty_name of 200 accepted, 201 rejected)
    PROCEDURE c01_boundaries;

    --%test(C02: impossible date, unpadded month and another valid month rejected; padded partition date accepted)
    PROCEDURE c02_boundaries;

    --%test(C03: lower case and empty segment rejected; segment surrounded by spaces accepted)
    PROCEDURE c03_boundaries;

    --%test(C04: NR accepted; C and lower case aaa rejected)
    PROCEDURE c04_boundaries;

    --%test(C05: y and empty rejected; N accepted)
    PROCEDURE c05_boundaries;

    --%test(C06: lower case, missing for CORPORATE and broken check digits rejected; SME without LEI and RETAIL with LEI accepted)
    PROCEDURE c06_boundaries;

    --%test(C07: FR accepted; fr and FRA rejected)
    PROCEDURE c07_boundaries;

    --%test(C08: every occurrence of a duplicate rejected, trailing space included; an occurrence failing C04 keeps C04)
    PROCEDURE c08_boundaries;

    --%test(the first failing rule in code order gives the reason code)
    PROCEDURE first_failing_rule_wins;

    --%test(C06: the 1,000 GLEIF codes pass; every same-class single-character change fails)
    PROCEDURE c06_gleif_sample;

    --%test(accepted rows reach silver trimmed and typed, 200 accented characters included; rejected rows do not)
    PROCEDURE accepted_rows_typed;

    --%test(R01: exposure_id of 30 characters accepted, 31 rejected; empty cpty_id rejected)
    PROCEDURE r01_boundaries;

    --%test(R02: 16 integer digits accepted, 17 rejected; 1e3, 1,50, 1.505 and a non-amount collateral rejected)
    PROCEDURE r02_boundaries;

    --%test(R03: -0.01 rejected; 0 and -0 accepted)
    PROCEDURE r03_boundaries;

    --%test(R04: LOAN accepted; loan rejected)
    PROCEDURE r04_boundaries;

    --%test(R05: unpadded month and another valid month rejected; partition date accepted)
    PROCEDURE r05_boundaries;

    --%test(R06: every occurrence of a duplicate rejected; an occurrence failing R02 keeps R02)
    PROCEDURE r06_boundaries;

    --%test(R07: exposures of a counterparty rejected by C04 or C08 or unknown rejected; an R02 fault keeps R02)
    PROCEDURE r07_boundaries;

    --%test(R08: 0.00 or empty amount without type accepted; 0.01 without type rejected)
    PROCEDURE r08_boundaries;

    --%test(R09: CASH and empty accepted; cash rejected)
    PROCEDURE r09_boundaries;

    --%test(R10: LOAN with undrawn 0.01 and GUARANTEE with drawn 0.01 rejected; UNDRAWN_LINE with both accepted)
    PROCEDURE r10_boundaries;

    --%test(R11: eur and USD rejected; EUR accepted)
    PROCEDURE r11_boundaries;

    --%test(every load reconciles exactly: bronze rows equal silver rows plus rejected rows)
    PROCEDURE reconciliation_exact;

    --%test(computing the rejects of a load twice replaces them and keeps the same count)
    PROCEDURE rejects_replaced_per_load;

    --%test(silver insertion refuses a load whose rejects were not computed)
    --%throws(-20202)
    PROCEDURE rejects_required_before_silver;
END ut_silver;
/
