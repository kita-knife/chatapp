"""User preferences module (per-user settings).

Schema: one row per user with a JSONB blob (`preferences`). Values are
deep-merged on update so a PATCH of `{"ui_language": "en"}` does not wipe
the rest of the user's preferences.
"""