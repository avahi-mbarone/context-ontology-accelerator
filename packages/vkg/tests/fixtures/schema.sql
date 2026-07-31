-- Schema for Ontop H2 in-memory validation (mirrors Athena insurance_lake.claims)
CREATE TABLE IF NOT EXISTS claims (
    claim_id VARCHAR(50) PRIMARY KEY,
    customer_id VARCHAR(50) NOT NULL,
    amount VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL,
    filed_date VARCHAR(20) NOT NULL
);
