- **Deploy prerequisite for the in-product AI-key page:** every product that
  enables it (`KEEL_LOCAL_AI_KEY=True`, or any standalone deployment showing
  the editable AI panel) must set `KEEL_ENCRYPTION_KEYS` on the service
  **before** rollout. Without it the panel now degrades to an admin-facing
  "not configured" message instead of 500ing — but users still can't save a
  key until the env var is set. Generate a key with
  `python -c "from keel.security.encryption import generate_key; print(generate_key())"`.
