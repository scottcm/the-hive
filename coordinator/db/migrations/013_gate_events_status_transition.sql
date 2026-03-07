-- Extend gate_name constraint to include G_status_transition for invalid transition audit trail.

ALTER TABLE hive.task_gate_events DROP CONSTRAINT IF EXISTS task_gate_events_gate_name_check;
ALTER TABLE hive.task_gate_events ADD CONSTRAINT task_gate_events_gate_name_check
    CHECK (gate_name IN (
        'G1_scope_lock',
        'G2_tdd_order',
        'G3_verification',
        'G4_review_separation',
        'G5_handoff_completeness',
        'G_start_dependencies',
        'G_status_transition'
    ));
