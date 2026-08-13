ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
CREATE OR REPLACE PACKAGE ut_silver AUTHID DEFINER AS
    --%suite(pkg_silver counterparty rules)

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

    --%test(silver insertion refuses a load whose rejects were not computed)
    --%throws(-20202)
    PROCEDURE rejects_required_before_silver;
END ut_silver;
/
