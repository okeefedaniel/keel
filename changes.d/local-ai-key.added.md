- **`KEEL_LOCAL_AI_KEY` opt-in** — a suite-mode product can now store each
  user's Anthropic key in its OWN database and manage it entirely in-product
  (Keel stays invisible — no click-out to `keel.docklabs.ai`). Off by default,
  so bumping the keel pin never changes AI-key behavior on a product that
  hasn't opted in. When set to `True`: the `AIPanel` renders the editable form
  in suite mode and writes the product-local `anthropic_api_key_encrypted`
  field; the `ai_key_prompt` link (`_ai_settings_url`) points at the in-product
  `/settings/ai/` instead of the IdP; and the AI gate (`_user_has_key`) treats
  the local field as the sole source of truth (ignoring the `ai_key_present`
  OIDC claim, which mirrors the *Keel identity's* key that the product can't
  call Anthropic with unless it holds a local copy). Standalone products are
  unaffected — they were already editable + local-first. New helper
  `keel.core.utils.local_ai_key_enabled()`.
