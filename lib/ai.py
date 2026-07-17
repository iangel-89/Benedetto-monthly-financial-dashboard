# ==============================================================================
# AI EXECUTIVE SUMMARY — Google Gemini (google-genai SDK)
#
# The previous version of this app used `google.generativeai`, which Google
# fully retired on 2025-11-30 in favor of the unified `google-genai` SDK —
# that's why "the AI" had stopped working. This module also never lets the
# model do arithmetic: every number in the prompt comes from lib.engine /
# lib.report, and Gemini is only asked to explain what the numbers mean.
# ==============================================================================
from __future__ import annotations

import pandas as pd

from .report import executive_summary

# Newest-first. "-latest" aliases track Google's current GA model, so this
# list keeps working as models are retired/renamed; pinned versions are the
# fallback if an alias ever disappears.
MODEL_CANDIDATES = [
    "gemini-flash-latest",
    "gemini-2.5-flash",
    "gemini-2.0-flash",
]


class AIError(RuntimeError):
    def __init__(self, friendly: str, technical: str = ""):
        super().__init__(friendly)
        self.friendly = friendly
        self.technical = technical or friendly


def _friendly_reason(e: Exception) -> str:
    s = str(e)
    if "API_KEY_INVALID" in s or "API key not valid" in s:
        return "That API key doesn't look valid. Double-check you copied it correctly from Google AI Studio."
    if "PERMISSION_DENIED" in s:
        return "This API key doesn't have permission to use the Gemini API."
    if "RESOURCE_EXHAUSTED" in s or "quota" in s.lower() or "rate limit" in s.lower():
        return "You've hit your Gemini usage quota or rate limit — try again in a bit."
    if "NOT_FOUND" in s and "model" in s.lower():
        return "The selected Gemini model isn't available for this key."
    if "DEADLINE_EXCEEDED" in s or "timeout" in s.lower():
        return "The request to Gemini timed out — try again."
    first_line = s.strip().splitlines()[0] if s.strip() else "Unknown error"
    return first_line[:180]


def _build_prompt(M: pd.DataFrame, entity: str, audit_entries: list) -> str:
    summary_table = executive_summary(M, entity).to_string(index=False)
    months = f"{M.index[0]} to {M.index[-1]}"

    flags = [a for a in audit_entries if a["Severity"] in ("ERROR", "WARNING")]
    flags_text = "\n".join(f"- [{a['Severity']}] {a['Finding']}" for a in flags) or "- None."

    return f"""You are a friendly financial advisor explaining a small business's numbers
to its owner, who has NO accounting or finance background. Avoid jargon; when you must
use a financial term (e.g. "EBITDA", "working capital"), define it in plain words the
first time you use it, in parentheses.

Company: {entity}
Period covered: {months}

KEY FIGURES (already calculated — do not recompute or contradict these numbers):
{summary_table}

DATA QUALITY NOTES (things to caveat if relevant, otherwise ignore):
{flags_text}

Write an executive summary with exactly these four short sections, each 2-4 sentences,
using the section headers verbatim as markdown headers (####):

#### How the business is doing
Plain-language read on revenue and profit trends.

#### Cash and financial health
Plain-language read on cash flow, debt, and whether the business could cover a bad month.

#### Watch out for
The one or two things that most deserve the owner's attention (risks, red flags, or data
quality caveats). If nothing is concerning, say so briefly.

#### What to consider next
Two to three concrete, practical suggestions a small business owner could actually act on.

Tone: warm, direct, and honest — like a trusted advisor, not a textbook. Never invent
numbers that are not in the KEY FIGURES above. Keep the whole response under 350 words."""


def _try_generate(client, prompt: str) -> tuple[str, str]:
    """Try each candidate model in order; return (text, model_used)."""
    errors = []
    friendly = None
    for model in MODEL_CANDIDATES:
        try:
            response = client.models.generate_content(model=model, contents=prompt)
            text = (response.text or "").strip()
            if text:
                return text, model
            errors.append(f"{model}: empty response")
        except Exception as e:  # noqa: BLE001 - surface every backend error to the user
            friendly = friendly or _friendly_reason(e)
            errors.append(f"{model}: {e}")
    raise AIError(friendly or "Gemini did not return a summary.",
                  technical="Tried: " + " | ".join(errors))


def generate_executive_summary(api_key: str, M: pd.DataFrame, entity: str,
                                audit_entries: list, model_override: str = "") -> tuple[str, str]:
    """Returns (summary_markdown, model_used). Raises AIError with a clear
    message on any failure (bad key, quota, retired model, network, ...)."""
    if not api_key:
        raise AIError("No Gemini API key was provided.")

    try:
        from google import genai
    except ImportError as e:
        raise AIError(
            "The 'google-genai' package is not installed. Add it to requirements.txt "
            "(it replaced the deprecated 'google-generativeai' package)."
        ) from e

    try:
        client = genai.Client(api_key=api_key)
    except Exception as e:  # noqa: BLE001
        raise AIError(f"Could not initialise the Gemini client: {e}") from e

    prompt = _build_prompt(M, entity, audit_entries)

    if model_override:
        try:
            response = client.models.generate_content(model=model_override, contents=prompt)
            text = (response.text or "").strip()
            if not text:
                raise AIError(f"Model '{model_override}' returned an empty response.")
            return text, model_override
        except AIError:
            raise
        except Exception as e:  # noqa: BLE001
            raise AIError(_friendly_reason(e), technical=f"Model '{model_override}' failed: {e}") from e

    return _try_generate(client, prompt)
