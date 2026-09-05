- **`keel.core.utils.fleet_product_hosts()`** returns the hosts of every peer in
  `KEEL_FLEET_PRODUCTS`, skipping malformed entries rather than raising.
- **`safe_redirect_url()` gained an optional `extra_hosts` argument** so a
  legitimate cross-product deep link can be allowed without a second copy of the
  open-redirect check. Backwards compatible — existing callers are unaffected.
  The notification click-through route uses it rather than carrying its own guard.
