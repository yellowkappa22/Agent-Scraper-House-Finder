CREATE TABLE IF NOT EXISTS property_status (
  property_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('new', 'in_process', 'contacted', 'ignored')),
  updated_at TEXT NOT NULL
);
