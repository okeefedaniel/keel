- **`KeelAccountAdapter.send_mail`** now hard-drops allauth's
  `account/email/unknown_account` mail suite-wide. That mail is what
  allauth sends (under its default `ACCOUNT_PREVENT_ENUMERATION = True`)
  to an address with **no account** when someone POSTs it to the public
  `/accounts/password/reset/` endpoint — which turned every product into
  an open email relay: an attacker scripted scraped third-party
  addresses through the reset form and each stranger got mail from
  `info@docklabs.ai`, torching the sending domain's reputation and
  landing real invitations in spam (97 of 100 outbound emails in the
  2026-07 window were these `[Harbor]/[Bounty] Unknown Account` sends).
  allauth's neutral "check your email" *response* is preserved, so there
  is no account-enumeration regression. Opt back in for a genuine
  standalone self-service deployment with `KEEL_EMAIL_UNKNOWN_ACCOUNTS =
  True` (no suite product needs it).
