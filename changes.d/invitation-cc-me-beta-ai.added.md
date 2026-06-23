- **TEMPORARY "CC me" checkbox on invitations.** The invite matrix form gains a
  `cc_me` checkbox; when ticked, the invitation email is CC'd to the hardcoded
  beta address `dok@dok.net` (constant `_BETA_CC_EMAIL` in
  `keel/accounts/views.py`) so the operator can see exactly what a beta invitee
  receives. No free-form CC field and no model/migration — the address is fixed
  to the superuser, so there's no way to misdirect the bearer accept token.
  **Remove the checkbox + constant once invites go to real customers.**
- **Beta-tester section in the invitation email.** When any product in the batch
  grants beta-tester status (`any_beta`), the email tells the invitee they're a
  beta tester and to submit feedback via the bottom-right feedback button (the
  `keel.requests` widget). Renders in both the HTML and plaintext bodies.
- **AI bring-your-own-key walkthrough in the invitation email.** When any product
  in the batch grants AI access (`any_ai`), the email walks the invitee through
  creating an Anthropic account, adding billing, generating an API key, and
  pasting it into their AI settings (`/settings/?panel=ai`, with a plain-text
  `Settings -> AI` fallback when the settings route isn't mounted). Both bodies
  updated; each section is omitted entirely when its flag is unset.
