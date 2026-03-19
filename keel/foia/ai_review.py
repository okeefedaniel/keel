"""
Keel FOIA AI Review — AI-powered classification review using Claude API.

Analyzes search results to flag:
- Records marked for release that may contain exempt information
- Records marked for withholding that may actually be responsive
- Records needing review that AI can pre-classify

Usage:
    from keel.foia.ai_review import review_classifications

    # Pass the FOIA request object and related models
    flags = review_classifications(
        foia_request=foia,
        search_results=foia.search_results.all(),
        determinations_qs=FOIADetermination.objects.filter(search_result__foia_request=foia),
        exemptions_qs=StatutoryExemption.objects.filter(is_active=True),
        api_key=settings.ANTHROPIC_API_KEY,
    )
"""
import json
import logging
import re

logger = logging.getLogger(__name__)


def review_classifications(foia_request, search_results, determinations_qs,
                          exemptions_qs, api_key):
    """Review all search results for a FOIA request using AI.

    Returns a list of dicts with flags for each result:
    {
        'result_id': uuid,
        'record_description': str,
        'current_classification': str,
        'current_determination': str or None,
        'ai_recommendation': 'release' | 'withhold' | 'partial_release' | 'needs_review',
        'ai_confidence': 'high' | 'medium' | 'low',
        'ai_reasoning': str,
        'flag': 'ok' | 'should_release' | 'should_withhold' | 'review_recommended',
        'flag_reason': str,
    }
    """
    if not api_key:
        return []

    if not search_results.exists():
        return []

    # Build determination lookup
    det_map = {}
    for det in determinations_qs.select_related('search_result'):
        det_map[det.search_result_id] = det

    # Get exemption reference text
    exemptions = list(exemptions_qs.values('subdivision', 'label'))
    exemption_ref = '\n'.join(f"  {e['subdivision']}: {e['label']}" for e in exemptions)

    # Build batch of records for AI review
    records_for_review = []
    for r in search_results:
        det = det_map.get(r.pk)
        records_for_review.append({
            'id': str(r.pk),
            'type': r.record_type,
            'description': r.record_description,
            'content': r.snapshot_content[:1500],
            'zone': r.snapshot_metadata.get('zone', 'unknown'),
            'pre_classification': r.pre_classification,
            'determination': det.decision if det else None,
            'exemptions_claimed': [str(e) for e in det.exemptions_claimed.all()] if det else [],
        })

    # Batch in groups of 10
    all_flags = []
    for i in range(0, len(records_for_review), 10):
        batch = records_for_review[i:i+10]
        flags = _review_batch(batch, foia_request.subject, exemption_ref, api_key)
        all_flags.extend(flags)

    return all_flags


def _review_batch(records, request_subject, exemption_ref, api_key):
    """Send a batch of records to Claude for classification review."""
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)

        records_json = json.dumps(records, indent=2)

        prompt = f"""You are a FOIA compliance attorney reviewing records for potential disclosure.

FOIA Request Subject: {request_subject}

Connecticut Statutory Exemptions (CT \u00a7 32-244):
{exemption_ref}

Review each record below and assess whether its current classification is correct.
For each record, provide:
- ai_recommendation: "release", "withhold", "partial_release", or "needs_review"
- ai_confidence: "high", "medium", or "low"
- ai_reasoning: 1-2 sentences explaining your assessment
- flag: "ok" (classification looks correct), "should_release" (currently withheld but should be released),
        "should_withhold" (currently released but contains exempt info), or "review_recommended"
- flag_reason: Brief explanation of the flag

Return ONLY a JSON array of objects, one per record, each with the record "id" and the fields above.

Records to review:
{records_json}"""

        message = client.messages.create(
            model='claude-sonnet-4-20250514',
            max_tokens=2048,
            messages=[{'role': 'user', 'content': prompt}],
        )

        text = message.content[0].text.strip()
        if text.startswith('```'):
            text = re.sub(r'^```(?:json)?\s*', '', text)
            text = re.sub(r'\s*```$', '', text)

        flags = json.loads(text)

        # Merge with original record data
        record_map = {r['id']: r for r in records}
        for flag in flags:
            rid = flag.get('id')
            if rid and rid in record_map:
                flag['record_description'] = record_map[rid]['description']
                flag['current_classification'] = record_map[rid]['pre_classification']
                flag['current_determination'] = record_map[rid]['determination']
                flag['result_id'] = rid

        return flags

    except Exception:
        logger.exception('AI FOIA review failed for batch')
        return []
