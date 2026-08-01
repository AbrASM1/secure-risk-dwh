ALTER SESSION SET CURRENT_SCHEMA = srdwh_owner;
DECLARE
    l_problems VARCHAR2(4000);
BEGIN
    WITH schemas AS (
        SELECT 'SRDWH_OWNER' AS deployed_schema FROM dual
        UNION ALL
        SELECT 'SRDWH_SEC' AS deployed_schema FROM dual
    ),

    problems AS (
        SELECT 'invalid ' || o.owner || '.' || o.object_name AS problem
        FROM dba_objects o
        INNER JOIN schemas s ON o.owner = s.deployed_schema
        WHERE o.status != 'VALID'
        UNION
        SELECT 'errors in ' || e.owner || '.' || e.name AS problem
        FROM dba_errors e
        INNER JOIN schemas s ON e.owner = s.deployed_schema
        UNION ALL
        SELECT 'no comment on ' || t.owner || '.' || t.table_name AS problem
        FROM dba_tab_comments t
        INNER JOIN schemas s ON t.owner = s.deployed_schema
        WHERE t.comments IS NULL AND t.table_name NOT LIKE 'BIN$%'
        UNION ALL
        SELECT 'no comment on ' || c.owner || '.' || c.table_name || '.' || c.column_name AS problem
        FROM dba_col_comments c
        INNER JOIN schemas s ON c.owner = s.deployed_schema
        WHERE c.comments IS NULL AND c.table_name NOT LIKE 'BIN$%'
    )

    SELECT listagg(problem, '; ' ON OVERFLOW TRUNCATE) WITHIN GROUP (ORDER BY problem)
    INTO l_problems
    FROM problems;
    IF l_problems IS NOT NULL THEN
        raise_application_error(-20001, substr('deploy check: ' || l_problems, 1, 2000));
    END IF;
END;
/
