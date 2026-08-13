ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;

CREATE TABLE ut_lei_gleif (
    lei VARCHAR2 (20 CHAR) NOT NULL
);

COMMENT ON TABLE ut_lei_gleif IS 'Test fixture, dev and ci only: 1,000 GLEIF LEI codes from db/tests/fixtures.';
COMMENT ON COLUMN ut_lei_gleif.lei IS 'LEI code.';

CREATE DIRECTORY srdwh_test_dir AS '/opt/srdwh/tests/fixtures';
GRANT READ ON DIRECTORY srdwh_test_dir TO srdwh_owner;

BEGIN
    EXECUTE IMMEDIATE 'CREATE TABLE ext_lei_gleif (lei VARCHAR2(20)) '
        || 'ORGANIZATION EXTERNAL (TYPE oracle_loader DEFAULT DIRECTORY srdwh_test_dir ACCESS PARAMETERS ('
        || 'RECORDS DELIMITED BY NEWLINE CHARACTERSET al32utf8 SKIP 1 NOBADFILE NODISCARDFILE NOLOGFILE '
        || 'FIELDS CSV WITHOUT EMBEDDED NOTRIM) LOCATION (''lei_gleif_sample.csv'')) REJECT LIMIT 0';
END;
/

INSERT INTO ut_lei_gleif (lei)
SELECT lei FROM ext_lei_gleif;
COMMIT;

DROP TABLE ext_lei_gleif PURGE;
DROP DIRECTORY srdwh_test_dir;
