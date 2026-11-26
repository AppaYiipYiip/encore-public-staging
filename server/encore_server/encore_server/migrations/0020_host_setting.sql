-- P3-06 slice 3 (docs/35 section 4): the Host's own choices, typed and allow-listed by the add-on manifest (`addons/`), in a table of their own.
-- It is NOT `setting`: that one is the server's internal state and holds its identity PRIVATE key and the key that signs song addresses; no route ever reads or writes it.
-- Order of truth: the Host's stored choice, else the environment variable, else the manifest's default.
--   key         `addon.<id>` for an add-on's state (runs | yours | off); other keys are named by the manifest
--   value       the choice, as text
--   updated_at  milliseconds
--   updated_by  the person id of the owner who chose, or `command` (the encore command on the computer)
CREATE TABLE host_setting (
  key        TEXT PRIMARY KEY,
  value      TEXT NOT NULL,
  updated_at INTEGER NOT NULL,
  updated_by TEXT NOT NULL
);
