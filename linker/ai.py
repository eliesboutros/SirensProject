"""LLM assist layer (optional) — the 'reads and explains' part.

Given a new incident and the matches the offline engine already found, this asks
Claude to write a short, plain-English linkage assessment: which past incidents
it most resembles and why, phrased the way an analyst would brief it. The LLM is
*only* handed structured facts the pipeline extracted plus the match scores — it
summarises and explains, it does not invent evidence.

This layer is entirely optional. If there is no API key, no internet, or the SDK
isn't installed, `available()` returns False and the web app simply hides the AI
panel and shows the offline results — nothing breaks. That keeps the tool's
"works fully offline" property intact; the LLM is an enhancement, not a crutch.

Setup (one time):
    pip install anthropic
    setx ANTHROPIC_API_KEY "sk-ant-..."     # Windows; reopen the terminal after
"""
from __future__ import annotations

import os

# Change this to trade quality for cost. Haiku is cheapest/fastest;
# Sonnet gives richer write-ups. Both are current API model strings.
DEFAULT_MODEL = "claude-sonnet-5"          # or "claude-haiku-4-5-20251001"

_SYSTEM = (
    "You are a decision-support assistant for counter-IED incident analysts. "
    "You are given (a) a NEW incident's extracted, structured facts and (b) the "
    "most similar PAST incidents already found by a link-analysis engine, with "
    "scores and the reasons the engine gave. Write a concise linkage assessment "
    "(120-180 words) in plain English: state which past incident(s) the new one "
    "most likely connects to and why, referencing the shared signature features "
    "and any shared identities. Ground every statement in the data provided; do "
    "not introduce facts that are not present. This is investigative "
    "decision-support, not a positive identification and not technical or "
    "device-handling guidance — end with a one-line reminder that a human analyst "
    "confirms any link."
)


def available() -> tuple[bool, str]:
    """(is_available, human-readable reason)."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False, "No ANTHROPIC_API_KEY set in the environment."
    try:
        import anthropic  # noqa: F401
    except Exception:
        return False, "The 'anthropic' package isn't installed (pip install anthropic)."
    return True, "ready"


def _fmt_incident(inc) -> str:
    feats = ", ".join(f"{f.facet}={f.value}" for f in inc.features) or "none"
    ents = []
    if inc.persons: ents.append("persons: " + ", ".join(sorted(inc.persons)))
    if inc.groups:  ents.append("groups: " + ", ".join(sorted(inc.groups)))
    if inc.phones:  ents.append("phones: " + ", ".join(sorted(inc.phones)))
    ent_str = "; ".join(ents) or "none"
    return (f"id={inc.incident_id} | date={inc.date or '?'} | "
            f"location={inc.location or '?'}\n  features: {feats}\n  entities: {ent_str}\n"
            f"  narrative: {inc.narrative.strip()[:600]}")


def _build_context(new_inc, structured, semantic) -> str:
    lines = ["=== NEW INCIDENT ===", _fmt_incident(new_inc), "",
             "=== TOP STRUCTURED MATCHES (taxonomy engine) ==="]
    if structured:
        for inc, link in structured:
            reasons = "; ".join(link.reasons) if link.reasons else "shared features"
            lines.append(f"[{link.score:.2f}] {inc.incident_id}: {reasons}")
    else:
        lines.append("(none above threshold)")
    lines += ["", "=== TOP MEANING MATCHES (semantic engine) ==="]
    if semantic:
        for inc, sim in semantic:
            lines.append(f"[{sim:.2f}] {inc.incident_id}: {inc.location or '?'} — "
                         f"{inc.narrative.strip()[:140]}")
    else:
        lines.append("(none)")
    return "\n".join(lines)


def assess(new_inc, structured, semantic, model: str = DEFAULT_MODEL) -> dict:
    """Return {'ok': bool, 'text': str|None, 'reason': str, 'model': str}."""
    ok, reason = available()
    if not ok:
        return {"ok": False, "text": None, "reason": reason, "model": model}
    try:
        import anthropic
        client = anthropic.Anthropic()
        context = _build_context(new_inc, structured, semantic)
        msg = client.messages.create(
            model=model,
            max_tokens=700,
            system=_SYSTEM,
            messages=[{"role": "user", "content":
                       f"Assess the linkage for this new incident.\n\n{context}"}],
        )
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text").strip()
        return {"ok": True, "text": text, "reason": "ok", "model": model}
    except Exception as e:  # network, auth, rate limit, bad model — never crash the app
        return {"ok": False, "text": None,
                "reason": f"LLM call failed: {type(e).__name__}: {e}", "model": model}
