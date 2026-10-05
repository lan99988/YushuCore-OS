CREATE TABLE operations (
    request_id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    resource_key TEXT NOT NULL,
    status TEXT NOT NULL,
    receipt TEXT,
    updated TEXT NOT NULL
);
CREATE TABLE locks (
    resource_key TEXT PRIMARY KEY,
    request_id TEXT NOT NULL
);
CREATE TABLE events (
    calendar_id TEXT NOT NULL,
    event_id TEXT NOT NULL,
    task_guid TEXT,
    snapshot TEXT NOT NULL,
    PRIMARY KEY (calendar_id, event_id)
);
PRAGMA user_version=1;
INSERT INTO operations VALUES (
    'legacy-request-1', 'legacy-fingerprint', 'request:legacy-request-1',
    'succeeded',
    '{"status":"succeeded","request_id":"legacy-request-1","message":"legacy receipt retained","resource":{},"data":null,"error":null}',
    '2025-01-02T03:04:05+00:00'
);
INSERT INTO locks VALUES ('legacy-resource:calendar-1', 'legacy-pending-request');
INSERT INTO events VALUES (
    'calendar-1', 'event-1', 'task-1',
    '{"title":"legacy event snapshot","start":"2025-01-02T09:00:00+08:00"}'
);
