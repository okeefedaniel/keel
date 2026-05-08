"""keel.ai — cross-product AI key handoff endpoint.

Mounts at ``/api/v1/ai/`` (see ``keel.ai.urls``). Provides:

- ``GET /api/v1/ai/key/`` — bearer-token authenticated, returns the
  calling user's plaintext Anthropic key for use within the request
  lifetime. Audited per fetch.

Products call this endpoint with the user's OIDC access token to
retrieve the cleartext key on demand. The plaintext is never put in
the JWT itself — the JWT only carries ``ai_key_present: bool``. This
keeps the key out of every product's session/cookie storage and
leaves Keel as the single source of truth for the credential.

Per the "direct-fetch" decision in the rollout plan, the alternative
proxy endpoint (forwarding to Anthropic with the stored key, never
returning plaintext to products) is rejected — the extra hop on every
streaming SearchChat request is not worth the marginal security
benefit, especially since the key is user-scoped (compromise is
bounded to one user).
"""

default_app_config = 'keel.ai.apps.KeelAIConfig'
