CREATE TRIGGER events_require_real_namespace
BEFORE INSERT ON events
WHEN length(NEW.id) < 11
  OR substr(NEW.id, 1, 9) <> 'real_evt_'
  OR NEW.id GLOB '*[^A-Za-z0-9_-]*'
BEGIN
    SELECT RAISE(ABORT, 'event ID namespace is invalid');
END;

CREATE TRIGGER events_keep_internal_identity
BEFORE UPDATE OF id, source_id ON events
WHEN NEW.id <> OLD.id OR NEW.source_id <> OLD.source_id
BEGIN
    SELECT RAISE(ABORT, 'event identity is immutable');
END;

CREATE TRIGGER provenance_matches_event_source
BEFORE INSERT ON event_provenance
WHEN NEW.source_id <> (SELECT source_id FROM events WHERE id = NEW.event_id)
BEGIN
    SELECT RAISE(ABORT, 'provenance source does not match event source');
END;

CREATE TRIGGER provenance_identity_is_immutable
BEFORE UPDATE OF event_id, source_id, external_ref ON event_provenance
WHEN NEW.event_id <> OLD.event_id
  OR NEW.source_id <> OLD.source_id
  OR NEW.external_ref IS NOT OLD.external_ref
BEGIN
    SELECT RAISE(ABORT, 'event provenance identity is immutable');
END;
