"""
Keel FOIA Workflow — Standard FOIA request lifecycle transitions.

This defines the complete FOIA workflow from receipt through response and appeal.
Products can use this directly or extend it.

Usage:
    from keel.foia.workflow import FOIA_WORKFLOW

    # Check available transitions for current user
    transitions = FOIA_WORKFLOW.get_available_transitions(request.status, user)

    # Execute a transition
    FOIA_WORKFLOW.execute(request, 'scope_defined', user=user)
"""

from keel.core.workflow import Transition, WorkflowEngine


FOIA_WORKFLOW = WorkflowEngine(transitions=[
    Transition(
        from_status='received',
        to_status='scope_defined',
        roles=['foia_staff', 'foia_manager'],
        label='Define Scope',
        description='Define search parameters for the FOIA request.',
    ),
    Transition(
        from_status='scope_defined',
        to_status='searching',
        roles=['foia_staff', 'foia_manager'],
        label='Begin Search',
        description='Start searching for responsive records.',
    ),
    Transition(
        from_status='searching',
        to_status='under_review',
        roles=['foia_staff', 'foia_manager'],
        label='Submit for Review',
        description='Submit search results for legal review.',
    ),
    Transition(
        from_status='under_review',
        to_status='searching',
        roles=['foia_manager'],
        label='Return to Search',
        description='Additional search needed based on review.',
        require_comment=True,
    ),
    Transition(
        from_status='under_review',
        to_status='package_ready',
        roles=['foia_attorney', 'foia_manager'],
        label='Approve Package',
        description='Legal review complete, package ready for senior review.',
    ),
    Transition(
        from_status='package_ready',
        to_status='senior_review',
        roles=['foia_manager'],
        label='Submit to Senior Review',
        description='Submit response package for senior leadership review.',
    ),
    Transition(
        from_status='senior_review',
        to_status='under_review',
        roles=['foia_manager', 'agency_admin', 'system_admin'],
        label='Return to Review',
        description='Senior leadership requests changes.',
        require_comment=True,
    ),
    Transition(
        from_status='senior_review',
        to_status='responded',
        roles=['foia_manager', 'agency_admin', 'system_admin'],
        label='Send Response',
        description='Approve and send final response to requester.',
    ),
    Transition(
        from_status='responded',
        to_status='appealed',
        roles=['foia_staff', 'foia_manager'],
        label='Record Appeal',
        description='Requester has filed an appeal.',
    ),
    Transition(
        from_status='responded',
        to_status='closed',
        roles=['foia_staff', 'foia_manager'],
        label='Close Request',
        description='Close the completed FOIA request.',
    ),
    Transition(
        from_status='appealed',
        to_status='closed',
        roles=['foia_manager'],
        label='Close After Appeal',
        description='Close the request after appeal resolution.',
    ),
])
