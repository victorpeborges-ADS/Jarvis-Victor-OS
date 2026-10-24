ALTER TABLE local_captures ADD COLUMN version INTEGER NOT NULL DEFAULT 1 CHECK (version >= 1);
ALTER TABLE local_captures ADD COLUMN revised_at TEXT NOT NULL DEFAULT '';
UPDATE local_captures SET revised_at = created_at WHERE revised_at = '';
