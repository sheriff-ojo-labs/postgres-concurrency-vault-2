-- 1. Create a non-privileged application role (cannot bypass RLS)
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'app_tenant_user') THEN
        CREATE ROLE app_tenant_user LOGIN PASSWORD 'tenant_secure_pass' NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
    END IF;
END
$$;

-- 2. Create multi-tenant ledger table
DROP TABLE IF EXISTS vault_accounts CASCADE;

CREATE TABLE vault_accounts (
    account_id VARCHAR(64) PRIMARY KEY,
    tenant_id VARCHAR(64) NOT NULL,
    balance NUMERIC(12, 2) NOT NULL CHECK (balance >= 0),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 3. Enforce Kernel-Level Row Level Security (including table owners)
ALTER TABLE vault_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE vault_accounts FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation_policy ON vault_accounts;

CREATE POLICY tenant_isolation_policy ON vault_accounts
    FOR ALL
    TO app_tenant_user
    USING (tenant_id = current_setting('app.current_tenant', true))
    WITH CHECK (tenant_id = current_setting('app.current_tenant', true));

-- 4. Grant strict table privileges to the restricted role
GRANT USAGE ON SCHEMA public TO app_tenant_user;
GRANT SELECT, INSERT, UPDATE ON vault_accounts TO app_tenant_user;

-- 5. Seed deterministic test records as admin before dropping privileges
INSERT INTO vault_accounts (account_id, tenant_id, balance) VALUES
    ('acc_alpha_01', 'tenant_a', 1000.00),
    ('acc_beta_01',  'tenant_b', 2500.00);
