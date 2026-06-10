"""Extract structured label fields from a label image via the vision model."""
from __future__ import annotations

import json
from typing import Any

from .openrouter import OpenRouterError, chat_vision_json, image_to_data_url

EXTRACTION_SYSTEM_PROMPT = """\
You are a meticulous TTB (Alcohol and Tobacco Tax and Trade Bureau) label-reading assistant.
You read the text printed on an alcohol-beverage label image and report exactly what is there.
Transcribe verbatim. Do NOT correct spelling, casing, or punctuation. Do NOT invent fields that
are not visible. The government health warning must be transcribed character-for-character,
preserving its exact capitalization.
"""

EXTRACTION_USER_TEXT = """\
Read this alcohol-beverage label and return ONLY a JSON object with these keys:

{
  "brand_name": string|null,
  "class_type": string|null,                       // e.g. "Kentucky Straight Bourbon Whiskey"
  "alcohol_content": string|null,                  // verbatim, e.g. "45% Alc./Vol. (90 Proof)"
  "abv_percent": number|null,                       // numeric ABV if determinable, else null
  "net_contents": string|null,                      // e.g. "750 mL"
  "producer_name_address": string|null,
  "country_of_origin": string|null,
  "government_warning_text": string|null,           // verbatim, preserve exact case & punctuation
  "government_warning_is_allcaps_header": boolean,   // is the literal "GOVERNMENT WARNING:" header in ALL CAPS on the label?
  "legibility_notes": string|null                    // note glare, angle, blur, or unreadable areas
}

Rules:
- If a field is not present or unreadable, use null (and mention it in legibility_notes).
- government_warning_text must be the EXACT text as printed, including the header. Do not normalize case.
- Return strictly valid JSON. No markdown, no commentary.
"""

_FIELDS = {
    "brand_name",
    "class_type",
    "alcohol_content",
    "abv_percent",
    "net_contents",
    "producer_name_address",
    "country_of_origin",
    "government_warning_text",
    "government_warning_is_allcaps_header",
    "legibility_notes",
}


def _coerce(raw: dict[str, Any]) -> dict[str, Any]:
    """Normalize the model output to the expected shape, tolerating omissions."""
    out: dict[str, Any] = {k: raw.get(k) for k in _FIELDS}
    # abv_percent may come back as a string like "45" or "45%".
    abv = out.get("abv_percent")
    if isinstance(abv, str):
        cleaned = abv.strip().rstrip("%").strip()
        try:
            out["abv_percent"] = float(cleaned)
        except ValueError:
            out["abv_percent"] = None
    if isinstance(out.get("government_warning_is_allcaps_header"), str):
        out["government_warning_is_allcaps_header"] = (
            out["government_warning_is_allcaps_header"].strip().lower() in {"true", "yes", "1"}
        )
    return out


def parse_extraction_json(content: str) -> dict[str, Any]:
    """Parse the model's JSON content, tolerating stray markdown fences."""
    text = content.strip()
    if text.startswith("```"):
        # Strip ```json ... ``` fences if the model added them anyway.
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
        text = text.strip()
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise OpenRouterError("Could not parse the label fields the model returned.") from exc
    if not isinstance(raw, dict):
        raise OpenRouterError("Model did not return a JSON object of label fields.")
    return _coerce(raw)


async def extract_label_fields(image_bytes: bytes, mime_type: str = "image/jpeg") -> dict[str, Any]:
    """Run one vision call and return the structured label fields."""
    data_url = image_to_data_url(image_bytes, mime_type)
    content = await chat_vision_json(
        system_prompt=EXTRACTION_SYSTEM_PROMPT,
        user_text=EXTRACTION_USER_TEXT,
        image_data_url=data_url,
    )
    return parse_extraction_json(content)
