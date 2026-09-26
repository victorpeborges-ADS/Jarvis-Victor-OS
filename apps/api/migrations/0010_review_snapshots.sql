ALTER TABLE mission_artifact_reviews ADD COLUMN artifact_snapshot_json TEXT;

UPDATE mission_artifact_reviews
SET artifact_snapshot_json = (
    SELECT artifact.value
    FROM missions AS mission, json_each(mission.document_json, '$.artifacts') AS artifact
    WHERE mission.id = mission_artifact_reviews.mission_id
      AND mission.owner = mission_artifact_reviews.owner
      AND json_extract(artifact.value, '$.id') = mission_artifact_reviews.artifact_id
    LIMIT 1
);

CREATE TRIGGER review_decisions_no_update
BEFORE UPDATE ON mission_review_decisions
BEGIN SELECT RAISE(ABORT, 'review decision ledger is append only'); END;

CREATE TRIGGER review_decisions_no_delete
BEFORE DELETE ON mission_review_decisions
BEGIN SELECT RAISE(ABORT, 'review decision ledger is append only'); END;
