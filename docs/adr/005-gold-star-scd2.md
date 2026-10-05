# ADR-005 Gold star schema with an SCD2 counterparty and monthly snapshots

- Status: accepted.
- Context: risk reporting compares months and needs the rating and segment valid at each as_of.
- Decision: counterparty dimension in SCD2 on segment, rating and default flag, SCD1 on name, LEI and country;
  exposure and RWA facts as monthly snapshots partitioned by as_of, a mart aggregated from the RWA facts.
- Consequences: a late correction rewinds facts and versions from the corrected as_of and rebuilds forward;
  amounts add across exposures, never across as_of.
