"""
Google Gemini API client for HeatGlow CRM.

Two uses:
  1. qualify_enquiry()  — score an enquiry 0-100 with structured JSON output
  2. improve_email()    — rewrite campaign email copy (Phase 5)

Model: gemini-2.0-flash-lite
Cost:  ~$0.0001 per qualification call
"""
import json
import logging
from dataclasses import dataclass
from typing import Optional

import google.generativeai as genai
from django.conf import settings

logger = logging.getLogger(__name__)

# ── Gemini setup ─────────────────────────────────────────────────────────────

def _get_model():
    """Return a configured Gemini model instance."""
    api_key = settings.GEMINI_API_KEY
    if not api_key:
        raise ValueError('GEMINI_API_KEY is not set in environment')
    genai.configure(api_key=api_key)
    return genai.GenerativeModel('gemini-2.0-flash-lite')


# ── Response types ────────────────────────────────────────────────────────────

@dataclass
class EnquiryQualificationResult:
    score: int                    # 0-100
    recommendation: str           # APPROVE | REJECT | MANUAL_REVIEW
    confidence: str               # HIGH | MEDIUM | LOW
    explanation: str              # plain English reason for Gareth
    flags: list[str]              # e.g. ['out_of_service_area', 'commercial']
    raw_response: Optional[str] = None

    def is_valid(self) -> bool:
        return (
            0 <= self.score <= 100
            and self.recommendation in ('APPROVE', 'REJECT', 'MANUAL_REVIEW')
            and self.confidence in ('HIGH', 'MEDIUM', 'LOW')
        )


# ── Service area and business rules ──────────────────────────────────────────

SERVICE_AREA_POSTCODES = [
    'CF3', 'CF5', 'CF10', 'CF11', 'CF14', 'CF15', 'CF23', 'CF24',
    'CF38', 'CF62', 'CF63', 'CF64', 'CF83',
    'NP10', 'NP18', 'NP19', 'NP20', 'NP44',
    'SA1', 'SA2', 'SA3', 'SA4',
    'HR1', 'HR2', 'HR3', 'HR4',
    'LD1', 'LD2', 'LD3',
    'SY15', 'SY16', 'SY17',
    'CH1', 'CH2', 'CH3', 'CH4',
]

ACCEPTED_JOB_TYPES = [
    'boiler service', 'boiler repair', 'boiler installation',
    'boiler replacement', 'central heating repair',
    'central heating installation', 'radiator installation',
    'radiator repair', 'hot water cylinder', 'gas safety certificate',
    'landlord gas safety', 'power flush', 'thermostat replacement',
    'emergency plumbing', 'leak repair', 'pipe repair',
    'tap replacement', 'shower installation', 'bathroom installation',
    'drain unblocking', 'heatshield annual service', 'heatshield',
    'plumbing', 'heating',
]

RED_FLAG_KEYWORDS = [
    'new build development', 'commercial property', 'restaurant',
    'warehouse', 'industrial unit', 'block of flats', 'hotel',
    'school', 'hospital', 'large commercial', 'multi-unit',
]

QUALIFICATION_PROMPT = """
You are an AI assistant helping HeatGlow Heating and Plumbing qualify customer enquiries.
HeatGlow is a small heating and plumbing company based in Cardiff, Wales.

YOUR JOB:
Assess whether this enquiry is a genuine, legitimate job that HeatGlow should take on.
Return a score from 0 to 100 and a recommendation.

HEATGLOW SERVICE AREA (postcodes they cover):
{service_area}

ACCEPTED JOB TYPES:
{job_types}

RED FLAGS (reasons to reject or review):
- Postcode is outside the service area listed above
- Job type is commercial, industrial, or outside their scope
- Description contains keywords suggesting commercial work: {red_flags}
- Description is suspiciously vague (3 words or less with no real detail)
- Customer seems to be a developer or property management company
- Duplicate enquiry (same name and postcode as another recent one)
- Request is for a service they do not offer

SCORING GUIDE:
90-100  = Clear approve. In service area, accepted job type, clear description.
70-89   = Approve with minor concerns. Probably fine but worth a quick check.
50-69   = Manual review. Something is unclear but not an outright reject.
30-49   = Manual review. Multiple concerns. Gareth should look carefully.
0-29    = Reject. Out of area, wrong job type, or suspicious.

ENQUIRY TO ASSESS:
Customer name:  {customer_name}
Postcode:       {postcode}
Job type:       {job_type}
Urgency:        {urgency}
Description:    {description}

RESPOND WITH ONLY THIS JSON — no other text, no markdown, no explanation outside the JSON:
{{
  "score": <integer 0-100>,
  "recommendation": "<APPROVE|REJECT|MANUAL_REVIEW>",
  "confidence": "<HIGH|MEDIUM|LOW>",
  "explanation": "<1-2 sentences explaining the score for Gareth — be specific>",
  "flags": [<list of short flag strings, empty array if none>]
}}

CONFIDENCE GUIDE:
HIGH   = You are very sure about the score (clear in-area job or clear out-of-area)
MEDIUM = Reasonable confidence but some ambiguity
LOW    = Significant uncertainty — description is vague or postcode is borderline
"""


# ── Main functions ────────────────────────────────────────────────────────────

def qualify_enquiry(
    customer_name: str,
    postcode: str,
    job_type: str,
    urgency: str,
    description: str,
) -> EnquiryQualificationResult:
    """
    Call Gemini to score a customer enquiry.

    Returns an EnquiryQualificationResult with score 0-100,
    recommendation (APPROVE/REJECT/MANUAL_REVIEW), confidence,
    explanation and flags.

    Falls back to rule-based scoring if Gemini is unavailable.
    """
    try:
        return _call_gemini(
            customer_name=customer_name,
            postcode=postcode,
            job_type=job_type,
            urgency=urgency,
            description=description,
        )
    except Exception as exc:
        logger.warning(
            'Gemini qualification failed, falling back to rules: %s', exc
        )
        return _rule_based_fallback(postcode, description, urgency)


def improve_email(subject: str, body_html: str) -> dict:
    """
    Use Gemini to improve campaign email copy.
    Returns { "subject": "...", "body_html": "..." }
    Phase 5 feature — stub for now.
    """
    try:
        model = _get_model()
        prompt = f"""
You are a copywriter for HeatGlow Heating and Plumbing.
Improve this email to be more engaging and personal while keeping it professional.
Keep the same message and length — just make it better.

Subject: {subject}

Body:
{body_html}

Return ONLY JSON in this format:
{{"subject": "improved subject", "body_html": "improved body html"}}
"""
        response = model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                response_mime_type='application/json',
                temperature=0.7,
            ),
        )
        return json.loads(response.text)
    except Exception as exc:
        logger.warning('Gemini email improvement failed: %s', exc)
        return {'subject': subject, 'body_html': body_html}


# ── Internal helpers ──────────────────────────────────────────────────────────

def _call_gemini(
    customer_name: str,
    postcode: str,
    job_type: str,
    urgency: str,
    description: str,
) -> EnquiryQualificationResult:
    """Make the actual Gemini API call."""
    model = _get_model()

    prompt = QUALIFICATION_PROMPT.format(
        service_area=', '.join(SERVICE_AREA_POSTCODES),
        job_types=', '.join(ACCEPTED_JOB_TYPES),
        red_flags=', '.join(RED_FLAG_KEYWORDS),
        customer_name=customer_name,
        postcode=postcode.upper(),
        job_type=job_type,
        urgency=urgency,
        description=description,
    )

    response = model.generate_content(
        prompt,
        generation_config=genai.types.GenerationConfig(
            response_mime_type='application/json',
            temperature=0.1,   # low temperature = consistent, deterministic output
            max_output_tokens=512,
        ),
    )

    raw_text = response.text.strip()
    logger.debug('Gemini raw response: %s', raw_text)

    # Parse JSON response
    try:
        data = json.loads(raw_text)
    except json.JSONDecodeError:
        # Try to extract JSON from the response if Gemini added surrounding text
        import re
        match = re.search(r'\{.*\}', raw_text, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise ValueError(f'Could not parse Gemini response as JSON: {raw_text[:200]}')

    result = EnquiryQualificationResult(
        score=int(data.get('score', 50)),
        recommendation=data.get('recommendation', 'MANUAL_REVIEW'),
        confidence=data.get('confidence', 'LOW'),
        explanation=data.get('explanation', ''),
        flags=data.get('flags', []),
        raw_response=raw_text,
    )

    # Validate the result
    if not result.is_valid():
        logger.warning('Gemini returned invalid result: %s', data)
        return _rule_based_fallback(postcode, description, urgency)

    logger.info(
        'Gemini scored enquiry: score=%d recommendation=%s confidence=%s',
        result.score, result.recommendation, result.confidence,
    )
    return result


def _rule_based_fallback(
    postcode: str,
    description: str,
    urgency: str,
) -> EnquiryQualificationResult:
    """
    Simple rule-based fallback when Gemini is unavailable.
    Same logic as the original stub — used as a safety net only.
    """
    postcode_upper = (postcode or '').upper()
    in_service_area = any(
        postcode_upper.startswith(p.replace(' ', ''))
        for p in SERVICE_AREA_POSTCODES
    )

    if not in_service_area:
        return EnquiryQualificationResult(
            score=15,
            recommendation='REJECT',
            confidence='HIGH',
            explanation=(
                f'Postcode {postcode} is outside the HeatGlow service area. '
                f'Service covers Cardiff, Newport and surrounding areas.'
            ),
            flags=['out_of_service_area'],
        )
    elif not description or len(description.strip()) < 20:
        return EnquiryQualificationResult(
            score=40,
            recommendation='MANUAL_REVIEW',
            confidence='LOW',
            explanation='Description is too short to assess the job accurately.',
            flags=['insufficient_description'],
        )
    elif urgency == 'emergency':
        return EnquiryQualificationResult(
            score=90,
            recommendation='APPROVE',
            confidence='HIGH',
            explanation='Emergency job in service area. Recommend immediate approval.',
            flags=[],
        )
    else:
        return EnquiryQualificationResult(
            score=75,
            recommendation='APPROVE',
            confidence='MEDIUM',
            explanation='Routine job in service area. Looks legitimate.',
            flags=[],
        )