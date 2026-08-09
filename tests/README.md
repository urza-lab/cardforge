Cross-cutting integration/smoke tests (e.g. a script that runs
`docker compose up` and hits `/api/health/ready` end-to-end) land here as
later phases add enough surface area to make that worthwhile. Backend unit
tests live in `backend/tests/`; frontend tests will live alongside frontend
source once introduced.
