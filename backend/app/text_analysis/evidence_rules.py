"""Deterministic evidence extraction used alongside—not instead of—the BERT model."""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class EvidenceRule:
    rule_id: str
    category: str
    pattern: re.Pattern[str]


RULES: tuple[EvidenceRule, ...] = (
    EvidenceRule("urgency_timer", "false_urgency", re.compile(r"\b(hurry|act now|last chance|ends? (in|soon)|time (is )?running out)\b", re.I)),
    EvidenceRule("urgency_countdown", "false_urgency", re.compile(r"\b\d{1,2}\s*(minutes?|hours?|mins?|hrs?)\b.*\b(left|remaining|only)\b|\b\d{1,2}:\d{2}:\d{2}\b", re.I)),
    EvidenceRule("scarcity_stock", "false_scarcity", re.compile(r"\bonly\s+(?:\d+|one|two|three|few)\s+(?:items?|units?|left|remaining|in stock)\b|\balmost sold out\b|\blow stock\b", re.I)),
    EvidenceRule("social_proof_activity", "social_proof", re.compile(r"\b\d+\s+(?:people|shoppers|customers|users)\s+(?:are )?(?:viewing|watching|added|bought|purchased)\b|\bsomeone (?:in|from)\b", re.I)),
    EvidenceRule("confirm_shaming_decline", "confirm_shaming", re.compile(r"\bno thanks\b.*\b(pay|miss|don't want|do not want|rather)\b|\b(?:i|we) (?:don't|do not) want to (?:save|protect|get)\b", re.I)),
    EvidenceRule("fear_pressure_risk", "fear_or_pressure", re.compile(r"\b(?:don't risk|do not risk|at risk|are you sure|lose access|without .* you could)\b", re.I)),
    EvidenceRule("misleading_absolute", "misleading_claim", re.compile(r"\b(?:guaranteed|proven|100%|always|never|completely free|no costs? ever)\b", re.I)),
    EvidenceRule("subscription_renewal", "subscription_manipulation", re.compile(r"\b(?:auto(?:matically)? renew|recurring billing|paid subscription|charged .* unless you cancel|free trial.*(?:cancel|charged))\b", re.I)),
    EvidenceRule("forced_consent", "forced_consent", re.compile(r"\b(?:must consent|agree to .*marketing|accept .*to continue|required consent|agree to receive)\b", re.I)),
    EvidenceRule("sneaking_addon", "sneaking", re.compile(r"\b(?:added to your order|preselected|selected by default|shipping insurance|purchase protection)\b", re.I)),
    EvidenceRule("obstruction_cancel", "obstruction", re.compile(r"\b(?:cancel(?:lation)? .*requires?|to cancel.*(?:call|phone|mail)|online cancellation is unavailable|contact support to cancel)\b", re.I)),
)


def evidence_for_text(text: str) -> dict[str, list[dict[str, str]]]:
    evidence: dict[str, list[dict[str, str]]] = {}
    for rule in RULES:
        match = rule.pattern.search(text)
        if match:
            evidence.setdefault(rule.category, []).append({"rule_id": rule.rule_id, "phrase": match.group(0)})
    return evidence
