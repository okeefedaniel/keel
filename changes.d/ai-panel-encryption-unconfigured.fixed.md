- **`AIPanel`** no longer 500s when the deployment has no encryption key
  configured. Saving a key writes `KeelUser.anthropic_api_key_encrypted`
  (an `EncryptedTextField`), which raises `ImproperlyConfigured` at
  `get_db_prep_save` when neither `KEEL_ENCRYPTION_KEYS` nor
  `KEEL_ENCRYPTION_KEY` is set — this hit Beacon prod on 2026-07-22 on the
  first in-product key save. The panel now probes `get_fernet()` up front
  (GET and POST), hides the key form, and renders an admin-facing fix-it
  message ("set `KEEL_ENCRYPTION_KEYS` on the service; generate one with
  `keel.security.encryption.generate_key()`") instead of crashing.
