"""Synthetic domain identifiers accepted by the local-only memory prototype."""

CANONICAL_DOMAIN_IDS = frozenset(
    {
        "dom_synthetic_a",
        "dom_synthetic_b",
        "dom_synthetic_c",
        "dom_synthetic_d",
        "dom_synthetic_e",
        "dom_synthetic_f",
        "dom_synthetic_g",
        "dom_synthetic_h",
    }
)

CANONICAL_CONNECTORS = frozenset({"calendar_sim", "mission_sim"})
CALENDAR_READ_RESOURCE = "calendar:synthetic-primary"
CALENDAR_INVENTORY_RESOURCE = "calendar:synthetic-inventory"
MISSION_READ_RESOURCE = "mission:read"
MISSION_WRITE_RESOURCE = "mission:write"
MISSION_REVIEW_RESOURCE = "mission:review"
CANONICAL_RESOURCES = {
    "calendar_sim": frozenset({CALENDAR_READ_RESOURCE, CALENDAR_INVENTORY_RESOURCE}),
    "mission_sim": frozenset({MISSION_READ_RESOURCE, MISSION_WRITE_RESOURCE, MISSION_REVIEW_RESOURCE}),
}
