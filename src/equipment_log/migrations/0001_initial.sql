-- Equipment, checklists, pre-use inspections, scheduled maintenance.

CREATE TABLE equipment (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    location TEXT NOT NULL DEFAULT '',
    out_of_service INTEGER NOT NULL DEFAULT 0,
    out_of_service_reason TEXT NOT NULL DEFAULT '',
    out_of_service_since TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE checklist (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL
);

CREATE TABLE checklist_item (
    id INTEGER PRIMARY KEY,
    checklist_id INTEGER NOT NULL REFERENCES checklist (id) ON DELETE CASCADE,
    position INTEGER NOT NULL,
    text TEXT NOT NULL,
    critical INTEGER NOT NULL DEFAULT 0,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE inspection (
    id INTEGER PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment (id),
    inspector TEXT NOT NULL,
    performed_at TEXT NOT NULL,
    passed INTEGER NOT NULL,
    notes TEXT NOT NULL DEFAULT ''
);

CREATE TABLE inspection_answer (
    inspection_id INTEGER NOT NULL REFERENCES inspection (id) ON DELETE CASCADE,
    item_text TEXT NOT NULL,
    critical INTEGER NOT NULL,
    answer TEXT NOT NULL CHECK (answer IN ('ok', 'fail', 'na')),
    position INTEGER NOT NULL
);

CREATE TABLE maintenance_task (
    id INTEGER PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment (id),
    title TEXT NOT NULL,
    interval_days INTEGER NOT NULL CHECK (interval_days > 0),
    last_done TEXT
);

CREATE TABLE maintenance_record (
    id INTEGER PRIMARY KEY,
    equipment_id INTEGER NOT NULL REFERENCES equipment (id),
    task_id INTEGER REFERENCES maintenance_task (id),
    done_on TEXT NOT NULL,
    done_by TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    returned_to_service INTEGER NOT NULL DEFAULT 0,
    recorded_at TEXT NOT NULL
);

CREATE INDEX inspection_equipment ON inspection (equipment_id, performed_at);
CREATE INDEX record_equipment ON maintenance_record (equipment_id, done_on);
