-- Automotive component warranty analytics - star-ish schema.
-- Two fact tables (production_batches, warranty_claims) and four dimensions.

CREATE TABLE plants (
    plant_id          INTEGER PRIMARY KEY,
    plant_name        TEXT    NOT NULL,
    state             TEXT    NOT NULL,
    commissioned_year INTEGER NOT NULL
);

CREATE TABLE suppliers (
    supplier_id           INTEGER PRIMARY KEY,
    supplier_name         TEXT    NOT NULL,
    tier                  TEXT    NOT NULL,
    baseline_defect_rate  REAL    NOT NULL
);

CREATE TABLE components (
    component_id   INTEGER PRIMARY KEY,
    component_name TEXT    NOT NULL,
    category       TEXT    NOT NULL,
    unit_cost_inr  INTEGER NOT NULL,
    supplier_id    INTEGER NOT NULL REFERENCES suppliers(supplier_id)
);

CREATE TABLE defect_types (
    defect_id       INTEGER PRIMARY KEY,
    defect_name     TEXT    NOT NULL,
    defect_category TEXT    NOT NULL,
    severity        TEXT    NOT NULL CHECK (severity IN ('High','Medium','Low'))
);

CREATE TABLE production_batches (
    batch_id        INTEGER PRIMARY KEY,
    component_id    INTEGER NOT NULL REFERENCES components(component_id),
    plant_id        INTEGER NOT NULL REFERENCES plants(plant_id),
    supplier_id     INTEGER NOT NULL REFERENCES suppliers(supplier_id),
    production_date TEXT    NOT NULL,
    units_produced  INTEGER NOT NULL,
    vehicle_model   TEXT    NOT NULL
);

CREATE TABLE warranty_claims (
    claim_id        INTEGER PRIMARY KEY,
    batch_id        INTEGER NOT NULL REFERENCES production_batches(batch_id),
    defect_id       INTEGER NOT NULL REFERENCES defect_types(defect_id),
    failure_date    TEXT    NOT NULL,
    claim_cost_inr  REAL    NOT NULL,
    resolution      TEXT    NOT NULL,
    days_to_failure INTEGER NOT NULL
);

CREATE INDEX idx_batches_date     ON production_batches(production_date);
CREATE INDEX idx_batches_supplier ON production_batches(supplier_id);
CREATE INDEX idx_claims_batch     ON warranty_claims(batch_id);
CREATE INDEX idx_claims_date      ON warranty_claims(failure_date);
