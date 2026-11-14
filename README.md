# PostgreSQL Multi-Tenant RLS & Deterministic `NOWAIT` Concurrency Vault

[![Verify Non-Privileged RLS & Deterministic NOWAIT Lock](https://github.com)](https://github.com)
[![License: MIT](https://shields.io)](LICENSE)

A production-grade reference implementation demonstrating **kernel-level multi-tenant Row Level Security (RLS)** under a strictly unprivileged PostgreSQL role alongside **deterministic row-level lock contention (`SELECT ... FOR UPDATE NOWAIT`)** to prevent race conditions and cross-tenant data leaks in high-concurrency financial and AI agent backends.

---

## Architecture Guarantees

1. **Unprivileged Role Enforcement (`NOSUPERUSER NOBYPASSRLS`)**
   * Provisioned role `app_tenant_user` cannot bypass RLS policies.
   * Table `vault_accounts` enforces both `ENABLE ROW LEVEL SECURITY` and `FORCE ROW LEVEL SECURITY`.
2. **Kernel-Level Cross-Tenant Isolation**
   * Session context is bound via `SET LOCAL app.current_tenant = '<tenant_id>'`.
   * Cross-tenant `SELECT` queries return **0 rows** and cross-tenant `UPDATE` statements affect **0 rows**.
3. **Deterministic Fail-Fast Concurrency (`SQLSTATE 55P03`)**
   * Uses `threading.Barrier(2)` across two independent database sessions to guarantee an active row-level lock collision.
   * Contending transactions fail deterministically with `psycopg2.errors.LockNotAvailable` (`SQLSTATE 55P03`) in sub-millisecond latency instead of blocking connection pools or corrupting ledger balances.
4. **Automated CI Verification & Inspectable Artifacts**
   * Every push runs against a live **PostgreSQL 16** container via GitHub Actions and uploads a timestamped `verification_report.json` build artifact.

---

## Repository Structure

* `database/schema.sql` — Provisioning for `app_tenant_user`, `vault_accounts` ledger schema, and `FORCE ROW LEVEL SECURITY` policies.
* `postgres_concurrency_test.py` — Automated verification suite asserting role privileges, cross-tenant read/write isolation, and deterministic `55P03` lock rejection.
* `.github/workflows/verify_rls_concurrency.yml` — Continuous integration pipeline running against PostgreSQL 16.
* `LICENSE` — MIT License.

---

## Local Reproduction

```bash
pip install psycopg2-binary
export ADMIN_DB_DSN="dbname=postgres user=postgres password=postgres host=localhost port=5432"
export TENANT_DB_DSN="dbname=postgres user=app_tenant_user password=tenant_secure_pass host=localhost port=5432"
python postgres_concurrency_test.py
```
