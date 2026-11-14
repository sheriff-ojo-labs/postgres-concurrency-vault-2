import json
import os
import threading
import time
from datetime import datetime, timezone
import psycopg2
from psycopg2 import errors

ADMIN_DSN = os.getenv("ADMIN_DB_DSN", "dbname=postgres user=postgres password=postgres host=localhost port=5432")
TENANT_DSN = os.getenv("TENANT_DB_DSN", "dbname=postgres user=app_tenant_user password=tenant_secure_pass host=localhost port=5432")


def setup_database():
    with psycopg2.connect(ADMIN_DSN) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            with open("database/schema.sql", "r", encoding="utf-8") as f:
                cur.execute(f.read())


def test_non_privileged_rls_isolation():
    """Verifies that app_tenant_user (NOSUPERUSER NOBYPASSRLS) cannot read or mutate another tenant's rows."""
    with psycopg2.connect(TENANT_DSN) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT current_user, usesuper, usebypassrls FROM pg_user WHERE usename = current_user;")
            role_name, is_super, can_bypass_rls = cur.fetchone()
            assert role_name == "app_tenant_user", f"Expected app_tenant_user, got {role_name}"
            assert is_super is False, "Role must not be SUPERUSER"
            assert can_bypass_rls is False, "Role must have NOBYPASSRLS"

            cur.execute("SET LOCAL app.current_tenant = 'tenant_a';")

            # 1. Cross-tenant SELECT must return 0 rows for tenant_b
            cur.execute("SELECT account_id, balance FROM vault_accounts WHERE tenant_id = 'tenant_b';")
            leaked_rows = cur.fetchall()
            assert len(leaked_rows) == 0, f"RLS breach: tenant_a read tenant_b rows: {leaked_rows}"

            # 2. Cross-tenant UPDATE must affect 0 rows
            cur.execute("UPDATE vault_accounts SET balance = 0 WHERE account_id = 'acc_beta_01';")
            assert cur.rowcount == 0, f"RLS breach: tenant_a mutated {cur.rowcount} tenant_b rows"

            # 3. Own-tenant SELECT must succeed
            cur.execute("SELECT account_id, balance FROM vault_accounts WHERE account_id = 'acc_alpha_01';")
            own_row = cur.fetchone()
            assert own_row is not None and float(own_row[1]) == 1000.00

    return {
        "role_verified": "app_tenant_user (NOSUPERUSER, NOBYPASSRLS)",
        "cross_tenant_select_rows": 0,
        "cross_tenant_update_rows": 0,
        "own_tenant_read_verified": True,
    }


def test_deterministic_nowait_conflict():
    """Deterministically forces a SQLSTATE 55P03 LockNotAvailable exception across two concurrent sessions."""
    barrier = threading.Barrier(2)
    results = {"holder_committed": False, "contender_sqlstate": None, "contender_latency_ms": None}

    def lock_holder():
        conn = psycopg2.connect(TENANT_DSN)
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL app.current_tenant = 'tenant_a';")
                cur.execute("SELECT balance FROM vault_accounts WHERE account_id = 'acc_alpha_01' FOR UPDATE;")
                row = cur.fetchone()
                assert row is not None
                barrier.wait(timeout=5)
                time.sleep(0.15)
                cur.execute("UPDATE vault_accounts SET balance = balance - 100.00 WHERE account_id = 'acc_alpha_01';")
            conn.commit()
            results["holder_committed"] = True
        finally:
            conn.close()

    def lock_contender():
        conn = psycopg2.connect(TENANT_DSN)
        try:
            with conn.cursor() as cur:
                cur.execute("SET LOCAL app.current_tenant = 'tenant_a';")
                barrier.wait(timeout=5)
                t0 = time.perf_counter()
                try:
                    cur.execute("SELECT balance FROM vault_accounts WHERE account_id = 'acc_alpha_01' FOR UPDATE NOWAIT;")
                except errors.LockNotAvailable as exc:
                    results["contender_sqlstate"] = exc.pgcode
                    results["contender_latency_ms"] = round((time.perf_counter() - t0) * 1000, 3)
                    conn.rollback()
        finally:
            conn.close()

    t1 = threading.Thread(target=lock_holder)
    t2 = threading.Thread(target=lock_contender)
    t1.start()
    t2.start()
    t1.join()
    t2.join()

    assert results["holder_committed"] is True, "Primary transaction failed to commit"
    assert results["contender_sqlstate"] == "55P03", f"Expected SQLSTATE 55P03, got {results['contender_sqlstate']}"
    return results


if __name__ == "__main__":
    setup_database()
    rls_report = test_non_privileged_rls_isolation()
    lock_report = test_deterministic_nowait_conflict()

    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "status": "PASSED",
        "rls_isolation_proof": rls_report,
        "deterministic_nowait_proof": lock_report,
    }

    with open("verification_report.json", "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(json.dumps(report, indent=2))
