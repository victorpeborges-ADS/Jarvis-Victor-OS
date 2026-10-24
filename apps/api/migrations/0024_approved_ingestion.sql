CREATE TABLE approved_roots (
    root_id TEXT PRIMARY KEY CHECK (
        length(root_id) BETWEEN 1 AND 32
        AND root_id NOT GLOB '*[^a-z0-9_-]*'
    ),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    revoked INTEGER NOT NULL CHECK (revoked IN (0, 1))
);

CREATE TABLE approved_files (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL,
    root_id TEXT NOT NULL REFERENCES approved_roots(root_id),
    relative_path TEXT NOT NULL CHECK (
        length(relative_path) BETWEEN 1 AND 180
        AND relative_path NOT GLOB '*..*'
        AND relative_path NOT GLOB '/*'
    ),
    fingerprint TEXT NOT NULL CHECK (length(fingerprint) = 64),
    size INTEGER NOT NULL CHECK (size BETWEEN 0 AND 4096),
    excerpt TEXT NOT NULL CHECK (length(excerpt) <= 4096),
    missing TEXT NOT NULL CHECK (length(missing) <= 512),
    UNIQUE (owner, domain_id, root_id, relative_path)
);

CREATE TABLE learned_proposals (
    id TEXT PRIMARY KEY CHECK (length(id) = 32 AND id NOT GLOB '*[^0-9a-f]*'),
    owner TEXT NOT NULL CHECK (owner = 'owner'),
    domain_id TEXT NOT NULL CHECK (domain_id IN (
        'dom_synthetic_a', 'dom_synthetic_b', 'dom_synthetic_c', 'dom_synthetic_d',
        'dom_synthetic_e', 'dom_synthetic_f', 'dom_synthetic_g', 'dom_synthetic_h'
    )),
    kind TEXT NOT NULL CHECK (kind IN ('memory', 'skill')),
    evidence TEXT NOT NULL CHECK (length(evidence) BETWEEN 1 AND 400),
    status TEXT NOT NULL CHECK (status IN ('pending', 'rejected')),
    regression INTEGER NOT NULL CHECK (regression IN (0, 1)),
    published INTEGER NOT NULL CHECK (published IN (0, 1))
);
