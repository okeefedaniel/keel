"""Notification types from all DockLabs products.

This module centralizes the notification type catalog so that the Keel
admin console can display routing for all products — even though each
product runs as a separate Django deployment.

Products should still register types in their own apps.py for runtime
dispatch.  This catalog is the source of truth for the admin matrix.
"""
from .registry import NotificationType, register


def register_all_product_types():
    """Register notification types for all DockLabs products."""
    _register_harbor_types()
    _register_beacon_types()
    _register_lookout_types()
    _register_bounty_types()
    _register_keel_types()


def _register_harbor_types():
    """Harbor Grants — 13 core + 4 signature types."""

    # --- Applications ---
    register(NotificationType(
        key='application_submitted',
        label='Application Submitted',
        description='A new grant application has been submitted for review.',
        category='Harbor — Applications',
        default_channels=['in_app', 'email'],
        default_roles=['system_admin', 'agency_admin', 'program_officer'],
        priority='medium',
    ))
    register(NotificationType(
        key='application_status_changed',
        label='Application Status Changed',
        description='An application status has been updated (approved, denied, revision requested).',
        category='Harbor — Applications',
        default_channels=['in_app', 'email'],
        default_roles=['applicant'],
        priority='high',
    ))

    # --- Awards ---
    register(NotificationType(
        key='award_created',
        label='Award Created',
        description='A new award has been created for an approved application.',
        category='Harbor — Awards',
        default_channels=['in_app', 'email'],
        default_roles=['applicant'],
        priority='high',
    ))
    register(NotificationType(
        key='amendment_requested',
        label='Amendment Requested',
        description='A new award amendment has been requested.',
        category='Harbor — Awards',
        default_channels=['in_app', 'email'],
        default_roles=['system_admin', 'agency_admin', 'program_officer'],
        priority='medium',
    ))
    register(NotificationType(
        key='signature_requested',
        label='Signature Requested',
        description='An award agreement has been sent for electronic signature.',
        category='Harbor — Awards',
        default_channels=['in_app', 'email'],
        default_roles=['applicant'],
        priority='high',
    ))
    register(NotificationType(
        key='signature_completed',
        label='Signature Completed',
        description='An award agreement has been signed.',
        category='Harbor — Awards',
        default_channels=['in_app', 'email'],
        default_roles=['system_admin', 'agency_admin', 'program_officer'],
        priority='high',
    ))

    # --- Financial ---
    register(NotificationType(
        key='drawdown_status_changed',
        label='Drawdown Status Changed',
        description='A cash drawdown request status has been updated.',
        category='Harbor — Financial',
        default_channels=['in_app', 'email'],
        default_roles=['applicant'],
        priority='high',
    ))

    # --- Reporting ---
    register(NotificationType(
        key='report_reviewed',
        label='Report Reviewed',
        description='A submitted report has been reviewed (approved, revision requested, or rejected).',
        category='Harbor — Reporting',
        default_channels=['in_app', 'email'],
        default_roles=['applicant'],
        priority='high',
    ))

    # --- Closeout ---
    register(NotificationType(
        key='closeout_initiated',
        label='Closeout Initiated',
        description='The closeout process has been initiated for an award.',
        category='Harbor — Closeout',
        default_channels=['in_app', 'email'],
        default_roles=['applicant'],
        priority='high',
    ))

    # --- Organizations ---
    register(NotificationType(
        key='organization_claim_submitted',
        label='Organization Claim Submitted',
        description='A user has claimed an organization and needs staff review.',
        category='Harbor — Organizations',
        default_channels=['in_app'],
        default_roles=['system_admin', 'agency_admin', 'program_officer'],
        priority='medium',
    ))
    register(NotificationType(
        key='organization_claim_reviewed',
        label='Organization Claim Reviewed',
        description='An organization claim has been approved or denied.',
        category='Harbor — Organizations',
        default_channels=['in_app'],
        default_roles=['applicant'],
        priority='high',
    ))

    # --- Users ---
    register(NotificationType(
        key='new_user_registered',
        label='New User Registration',
        description='A new user has registered on the platform.',
        category='Harbor — Users',
        default_channels=['in_app'],
        default_roles=['system_admin'],
        priority='medium',
    ))

    # --- AI Matching ---
    register(NotificationType(
        key='grant_match_found',
        label='AI Grant Match Found',
        description='The AI matching engine found a relevant grant opportunity.',
        category='Harbor — Matching',
        default_channels=['in_app', 'email'],
        default_roles=['applicant', 'federal_coordinator'],
        priority='medium',
    ))

    # --- Signatures ---
    register(NotificationType(
        key='signature_required',
        label='Signature Required',
        description='You are the next signer in a document signing flow.',
        category='Harbor — Signatures',
        default_channels=['in_app', 'email'],
        default_roles=['applicant', 'system_admin', 'agency_admin'],
        priority='high',
        allow_mute=False,
    ))
    register(NotificationType(
        key='signing_complete',
        label='Signing Complete',
        description='All signatures have been collected for a document.',
        category='Harbor — Signatures',
        default_channels=['in_app', 'email'],
        default_roles=['system_admin', 'agency_admin', 'program_officer'],
        priority='high',
    ))
    register(NotificationType(
        key='signing_declined',
        label='Signature Declined',
        description='A signer has declined to sign a document.',
        category='Harbor — Signatures',
        default_channels=['in_app', 'email'],
        default_roles=['system_admin', 'agency_admin', 'program_officer'],
        priority='high',
    ))
    register(NotificationType(
        key='signature_reminder',
        label='Signature Reminder',
        description='A reminder that your signature is needed.',
        category='Harbor — Signatures',
        default_channels=['in_app', 'email'],
        default_roles=['applicant', 'system_admin', 'agency_admin'],
        priority='high',
    ))


def _register_beacon_types():
    """Beacon CRM — planned notification types."""
    register(NotificationType(
        key='foia_request_received',
        label='FOIA Request Received',
        description='A new FOIA request has been submitted.',
        category='Beacon — FOIA',
        default_channels=['in_app', 'email'],
        default_roles=['foia_officer', 'admin'],
        priority='high',
    ))
    register(NotificationType(
        key='foia_deadline_approaching',
        label='FOIA Deadline Approaching',
        description='A FOIA request deadline is approaching.',
        category='Beacon — FOIA',
        default_channels=['in_app', 'email', 'sms'],
        default_roles=['foia_officer', 'admin'],
        priority='urgent',
    ))
    register(NotificationType(
        key='contact_activity_logged',
        label='Contact Activity Logged',
        description='A new interaction has been logged for a contact.',
        category='Beacon — CRM',
        default_channels=['in_app'],
        default_roles=['admin', 'staff'],
        priority='low',
    ))
    register(NotificationType(
        key='pipeline_stage_changed',
        label='Pipeline Stage Changed',
        description='A pipeline item has moved to a new stage.',
        category='Beacon — CRM',
        default_channels=['in_app'],
        default_roles=['admin', 'staff'],
        priority='medium',
    ))


def _register_lookout_types():
    """Lookout Legislative — planned notification types."""
    register(NotificationType(
        key='bill_status_changed',
        label='Bill Status Changed',
        description='A tracked bill has changed status or advanced.',
        category='Lookout — Bills',
        default_channels=['in_app', 'email'],
        default_roles=['admin', 'analyst', 'staff'],
        priority='high',
    ))
    register(NotificationType(
        key='hearing_scheduled',
        label='Hearing Scheduled',
        description='A public hearing has been scheduled for a tracked bill.',
        category='Lookout — Bills',
        default_channels=['in_app', 'email', 'sms'],
        default_roles=['admin', 'analyst', 'staff'],
        priority='high',
    ))
    register(NotificationType(
        key='testimony_deadline',
        label='Testimony Deadline Approaching',
        description='The testimony submission deadline is approaching.',
        category='Lookout — Testimony',
        default_channels=['in_app', 'email', 'sms'],
        default_roles=['admin', 'analyst'],
        priority='urgent',
    ))
    register(NotificationType(
        key='new_bill_matched',
        label='New Bill Matched',
        description='A newly filed bill matches your tracking criteria.',
        category='Lookout — Bills',
        default_channels=['in_app', 'email'],
        default_roles=['admin', 'analyst', 'staff'],
        priority='medium',
    ))


def _register_bounty_types():
    """Bounty Federal Grants — discovery and matching notifications."""
    register(NotificationType(
        key='grant_match_high_score',
        label='High-Score Grant Match',
        description='The AI matching engine found a highly relevant federal grant opportunity.',
        category='Bounty — Matching',
        default_channels=['in_app', 'email'],
        default_roles=['coordinator', 'analyst'],
        priority='high',
    ))
    register(NotificationType(
        key='opportunity_status_changed',
        label='Tracked Opportunity Status Changed',
        description='A federal opportunity you are tracking has changed status.',
        category='Bounty — Tracking',
        default_channels=['in_app'],
        default_roles=['coordinator', 'analyst'],
        priority='medium',
    ))
    register(NotificationType(
        key='harbor_push_completed',
        label='Opportunity Pushed to Harbor',
        description='An awarded opportunity has been successfully pushed to Harbor as a GrantProgram.',
        category='Bounty — Integration',
        default_channels=['in_app'],
        default_roles=['coordinator', 'admin'],
        priority='medium',
    ))


def _register_keel_types():
    """Keel platform — admin/system notification types."""
    register(NotificationType(
        key='change_request_submitted',
        label='Change Request Submitted',
        description='A beta user has submitted a change request.',
        category='Keel — Platform',
        default_channels=['in_app', 'email'],
        default_roles=['admin', 'system_admin'],
        priority='medium',
    ))
    register(NotificationType(
        key='security_alert',
        label='Security Alert',
        description='A security issue has been detected by the audit system.',
        category='Keel — Platform',
        default_channels=['in_app', 'email', 'sms'],
        default_roles=['admin', 'system_admin'],
        priority='urgent',
        allow_mute=False,
    ))
    register(NotificationType(
        key='invitation_accepted',
        label='Invitation Accepted',
        description='A user has accepted a platform invitation.',
        category='Keel — Platform',
        default_channels=['in_app'],
        default_roles=['admin', 'system_admin'],
        priority='low',
    ))
    register(NotificationType(
        key='test_suite_failure',
        label='Test Suite Failure',
        description='The nightly test or security audit has detected failures.',
        category='Keel — Platform',
        default_channels=['in_app', 'email'],
        default_roles=['admin', 'system_admin'],
        priority='high',
    ))
