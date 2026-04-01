"""
Calendar provider registry.

Each provider exposes four functions:
    create_event(user, title, start, end, location, description, metadata) -> (external_id, error)
    update_event(external_id, user, **fields) -> (success, error)
    delete_event(external_id, user) -> (success, error)
    check_availability(user, start, end) -> (available, conflicts, error)
"""
from .google import google_provider
from .microsoft import microsoft_provider

PROVIDERS = {
    'google': google_provider,
    'microsoft': microsoft_provider,
}
