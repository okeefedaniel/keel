- **Login-time AI-key hydration** (companion to `KEEL_LOCAL_AI_KEY`) — on
  products that store the key locally, the SSO adapter now does a one-shot
  fetch of the user's Anthropic key from Keel at login and copies it into the
  product-local `anthropic_api_key_encrypted` field, delivering "enter once,
  see everywhere" with **zero tokens at rest**. It spends the login-fresh
  access token allauth holds in memory (`sociallogin.token`, available even
  with `SOCIALACCOUNT_STORE_TOKENS=False`), then discards it. Runs only when
  the local field is empty (never clobbers an in-product edit or a prior
  hydration) and only for the Keel provider; entirely best-effort so it can
  never block login. New helper `keel.core.ai.fetch_ai_key_with_token()`
  (same HTTPS + host-allowlist + no-redirect transport guards as the stored-
  token path). Requires the login token to carry the `ai` scope.
