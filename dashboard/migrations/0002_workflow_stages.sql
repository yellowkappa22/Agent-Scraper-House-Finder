CREATE TABLE property_status_next (
  property_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (
    status IN (
      'new',
      'in_process',
      'contacted',
      'viewing_confirmed',
      'waiting_for_selection',
      'failed',
      'ignored'
    )
  ),
  updated_at TEXT NOT NULL
);

INSERT INTO property_status_next (property_id, status, updated_at)
SELECT property_id, status, updated_at
FROM property_status;

DROP TABLE property_status;

ALTER TABLE property_status_next RENAME TO property_status;
