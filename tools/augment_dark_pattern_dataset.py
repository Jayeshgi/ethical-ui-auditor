from __future__ import annotations

import csv
import json
import random
import re
from collections import Counter
from itertools import product
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT_ROOT / "data" / "raw" / "darkpatterndataset.csv"
OUTPUT_DIR = PROJECT_ROOT / "dataset_output"
OUTPUT = OUTPUT_DIR / "darkpatterndataset_augmented.csv"
SUMMARY = OUTPUT_DIR / "augmentation_summary.json"
TARGET_PER_DARK_CATEGORY = 250
SEED = 20260807


DIRECT_MAP = {
    "Not Dark Pattern": "neutral",
    "Urgency": "false_urgency",
    "Scarcity": "false_scarcity",
    "Social Proof": "social_proof",
    "Sneaking": "sneaking",
    "Obstruction": "obstruction",
    "Forced Action": "forced_consent",
}


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def dedupe_key(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", normalize_text(text).lower()).strip()


def map_misdirection(text: str) -> str:
    lowered = normalize_text(text).lower()
    confirm_markers = (
        "no thanks",
        "no, thank",
        "no thank",
        "i don't want",
        "i dont want",
        "i do not want",
        "i'd rather",
        "i’d rather",
        "i'll rather",
        "i’ll rather",
        "i prefer to pay",
        "i'll pay full",
        "i’ll pay full",
        "paying full price",
        "shop without a discount",
        "i don't like",
        "i don’t like",
        "i dont like",
        "i don't feel lucky",
        "i don’t feel lucky",
        "i definitely measured correctly",
    )
    if any(marker in lowered for marker in confirm_markers):
        return "confirm_shaming"
    return "misleading_claim"


def normalized_category(original_category: str, text: str) -> str:
    if original_category == "Misdirection":
        return map_misdirection(text)
    return DIRECT_MAP[original_category]


def combinations(templates: list[str], **values: list[str]) -> list[str]:
    keys = list(values)
    rows: list[str] = []
    for template in templates:
        used = [key for key in keys if "{" + key + "}" in template]
        for selected in product(*(values[key] for key in used)):
            rows.append(template.format(**dict(zip(used, selected))))
    return rows


def expand_for_ui_context(category: str, rows: list[str]) -> list[str]:
    prefixes = {
        "confirm_shaming": [
            "", "Before you leave: ", "Decline option: ", "No-offer option: ", "Dismiss message: ",
            "Exit choice: ", "Skip option: ", "Reject offer: ", "Continue without offer: ",
        ],
        "fear_or_pressure": ["", "Account warning: ", "Checkout warning: ", "Important: ", "Protection notice: "],
        "misleading_claim": ["", "Featured claim: ", "Promotional claim: ", "Product promise: ", "Exclusive claim: "],
        "subscription_manipulation": [
            "", "Membership terms: ", "Trial notice: ", "Subscription details: ", "Billing notice: ",
            "Renewal notice: ", "Member pricing: ", "Plan details: ",
        ],
        "forced_consent": ["", "Required consent: ", "Continue notice: ", "Registration condition: ", "Access requirement: "],
        "sneaking": ["", "Order update: ", "Cart notice: ", "Checkout summary: ", "Preselected option: "],
        "obstruction": [
            "", "Cancellation policy: ", "Account closure notice: ", "Membership exit terms: ",
            "Service termination notice: ", "Cancellation instructions: ", "Close-account requirement: ",
            "Membership cancellation: ", "Exit process: ",
        ],
    }
    if category not in prefixes:
        return rows
    return [prefix + row for row in rows for prefix in prefixes[category]]


def candidate_texts() -> dict[str, list[str]]:
    data: dict[str, list[str]] = {}

    data["false_urgency"] = combinations(
        [
            "{lead}! This {offer} ends in {duration}.",
            "Complete your {action} within {duration} or the {offer} will disappear.",
            "{lead}—your reserved {item} expires in {duration}.",
            "Final chance: claim the {offer} before the timer reaches zero.",
        ],
        lead=["Hurry", "Act now", "Don't wait", "Time is running out", "Last chance"],
        offer=["private discount", "special price", "exclusive offer", "checkout bonus"],
        duration=["two minutes", "five minutes", "ten minutes", "thirty seconds"],
        action=["purchase", "registration", "upgrade", "booking"],
        item=["price", "discount", "booking", "cart"],
    )

    data["false_scarcity"] = combinations(
        [
            "Only {count} {item} left—order before they are gone.",
            "{percent}% claimed; just {count} remain at this price.",
            "Almost sold out: {count} {item} still available.",
        ],
        count=["one", "two", "three", "four", "five"],
        item=["items", "units", "seats", "rooms", "passes"],
        percent=["82", "89", "93", "96", "98"],
    )

    data["social_proof"] = combinations(
        [
            "{count} people are viewing this {item} right now.",
            "Someone in {place} purchased this {item} {time} ago.",
            "{count} shoppers added this {item} to their cart today.",
        ],
        count=["7", "18", "34", "62", "103"],
        item=["product", "plan", "room", "course", "ticket"],
        place=["Mumbai", "Delhi", "London", "Toronto", "Sydney"],
        time=["one minute", "three minutes", "ten minutes", "an hour"],
    )

    data["confirm_shaming"] = combinations(
        [
            "No thanks, I'd rather {negative}.",
            "I don't want to {action}.",
            "Continue without {gerund}.",
            "No, I prefer to {action}.",
        ],
        negative=[
            "pay full price",
            "miss this opportunity",
            "leave my account unprotected",
            "lose my discount",
            "stay uninformed",
        ],
        action=[
            "save money",
            "protect my purchase",
            "receive the free benefit",
            "get exclusive deals",
            "make the smart choice",
        ],
        gerund=[
            "saving money",
            "protecting my purchase",
            "receiving the free benefit",
            "getting exclusive deals",
            "making the smart choice",
        ],
    )

    data["fear_or_pressure"] = combinations(
        [
            "Without {gerund}, you could {harm}.",
            "Are you sure? Leaving now may {harm}.",
            "Don't risk {noun_harm}; {action} immediately.",
            "Your {asset} may be at risk unless you {action}.",
        ],
        action=[
            "add protection",
            "upgrade now",
            "verify your account",
            "enable the service",
            "complete this step",
        ],
        gerund=[
            "adding protection",
            "upgrading now",
            "verifying your account",
            "enabling the service",
            "completing this step",
        ],
        harm=[
            "lose your progress",
            "miss important protection",
            "put your purchase at risk",
            "lose access to your benefits",
            "face unexpected problems",
        ],
        noun_harm=[
            "losing your progress",
            "missing important protection",
            "putting your purchase at risk",
            "losing access to your benefits",
            "unexpected problems",
        ],
        asset=["account", "purchase", "device", "booking", "personal information"],
    )

    data["misleading_claim"] = combinations(
        [
            "This {item} is guaranteed to {result}.",
            "The only {item} proven to {result}.",
            "{percent}% guaranteed results with absolutely no conditions.",
            "Completely free {item}—no costs ever apply.",
        ],
        item=["plan", "product", "service", "treatment", "membership"],
        result=[
            "save you money",
            "solve the problem",
            "double your results",
            "eliminate every risk",
            "work immediately",
        ],
        percent=["100", "99", "98", "95"],
    )

    data["subscription_manipulation"] = combinations(
        [
            "Start your {trial}; it automatically becomes a {frequency} paid subscription unless you cancel.",
            "Get {benefit} today and continue at {price} per {period} after the introductory period.",
            "By continuing, you enrol in automatic {frequency} billing until cancellation is completed.",
            "Your membership renews automatically at {price}; cancellation requires contacting support.",
        ],
        trial=["free trial", "discounted trial", "seven-day trial", "premium trial"],
        frequency=["monthly", "annual", "weekly"],
        period=["month", "year", "week"],
        benefit=["free delivery", "premium access", "member pricing", "a trial box"],
        price=["$9.99", "$19.99", "$39.99", "$79.99"],
    )

    data["forced_consent"] = combinations(
        [
            "By selecting {action}, you agree to {consent}.",
            "To continue, you must consent to {consent}.",
            "Accept {consent} to access the {feature}.",
            "I agree to {consent} and wish to proceed with {action}.",
        ],
        action=["Continue", "Create account", "Get my quote", "Download", "Submit order"],
        consent=[
            "marketing emails from selected partners",
            "promotional calls and automated messages",
            "sharing my information with advertising partners",
            "personalised advertising across services",
            "receiving promotional offers by email and SMS",
        ],
        feature=["website", "download", "account", "service", "requested information"],
    )

    data["sneaking"] = combinations(
        [
            "{addon} added to your order for {price}.",
            "Your total includes {addon}: {price}.",
            "Continue with the preselected {addon} for {price}.",
            "Complimentary trial included; {price} recurring charge begins after {duration} unless cancelled.",
        ],
        addon=[
            "shipping protection",
            "priority handling",
            "purchase insurance",
            "premium support",
            "a charitable contribution",
        ],
        price=["$1.99", "$2.99", "$4.99", "$7.99", "$12.99"],
        duration=["seven days", "fourteen days", "one month"],
    )

    data["obstruction"] = combinations(
        [
            "To cancel, call {phone_window}; online cancellation is unavailable.",
            "You can join online, but cancellation requires {requirement}.",
            "Before closing your account, complete {steps} separate confirmation steps.",
            "Cancellation requests are accepted only {window} and may take {duration} to process.",
        ],
        phone_window=[
            "support between 9:00 and 10:00 AM",
            "our retention team during business hours",
            "customer service on weekdays",
            "the membership desk during a one-hour window",
        ],
        requirement=[
            "a telephone request",
            "a posted written request",
            "a live-agent conversation",
            "identity documents sent by email",
        ],
        steps=["five", "six", "seven", "eight"],
        window=["by telephone", "during weekday business hours", "through postal mail", "through a support agent"],
        duration=["ten business days", "two weeks", "thirty days", "six weeks"],
    )

    for category, rows in list(data.items()):
        data[category] = expand_for_ui_context(category, rows)
    return data


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    with SOURCE.open("r", encoding="utf-8-sig", newline="") as handle:
        originals = list(csv.DictReader(handle))

    seen: set[str] = set()
    output_rows: list[dict[str, str]] = []
    duplicates_removed = 0

    for index, row in enumerate(originals, start=1):
        text = normalize_text(row["text"])
        key = dedupe_key(text)
        if key in seen:
            duplicates_removed += 1
            continue
        seen.add(key)
        original_category = row["Pattern Category"].strip()
        category = normalized_category(original_category, text)
        review_status = "original_label"
        if original_category == "Misdirection":
            review_status = "mapped_needs_review"
        output_rows.append(
            {
                "record_id": f"original-{index:05d}",
                "page_id": row["page_id"].strip(),
                "text": text,
                "label": row["label"].strip(),
                "Pattern Category": category,
                "original_category": original_category,
                "source": "original",
                "review_status": review_status,
                "split_eligibility": "train_validation_test",
            }
        )

    before_synthetic = Counter(row["Pattern Category"] for row in output_rows)
    candidates = candidate_texts()
    rng = random.Random(SEED)
    synthetic_added: Counter[str] = Counter()

    dark_categories = [
        "false_urgency",
        "false_scarcity",
        "social_proof",
        "confirm_shaming",
        "fear_or_pressure",
        "misleading_claim",
        "subscription_manipulation",
        "forced_consent",
        "sneaking",
        "obstruction",
    ]

    for category in dark_categories:
        required = max(0, TARGET_PER_DARK_CATEGORY - before_synthetic[category])
        pool = [normalize_text(text) for text in candidates[category]]
        rng.shuffle(pool)
        unique_pool = []
        for text in pool:
            key = dedupe_key(text)
            if key not in seen:
                seen.add(key)
                unique_pool.append(text)
        if len(unique_pool) < required:
            raise RuntimeError(
                f"Not enough unique synthetic candidates for {category}: "
                f"need {required}, found {len(unique_pool)}"
            )
        for text in unique_pool[:required]:
            synthetic_added[category] += 1
            output_rows.append(
                {
                    "record_id": f"synthetic-{category}-{synthetic_added[category]:04d}",
                    "page_id": "",
                    "text": text,
                    "label": "1",
                    "Pattern Category": category,
                    "original_category": "",
                    "source": "synthetic",
                    "review_status": "pending_review",
                    "split_eligibility": "train_only",
                }
            )

    fieldnames = [
        "record_id",
        "page_id",
        "text",
        "label",
        "Pattern Category",
        "original_category",
        "source",
        "review_status",
        "split_eligibility",
    ]
    with OUTPUT.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output_rows)

    final_counts = Counter(row["Pattern Category"] for row in output_rows)
    summary = {
        "source_file": str(SOURCE),
        "output_file": str(OUTPUT),
        "seed": SEED,
        "source_row_count": len(originals),
        "exact_or_normalized_duplicates_removed": duplicates_removed,
        "normalized_original_row_count": sum(before_synthetic.values()),
        "synthetic_row_count": sum(synthetic_added.values()),
        "final_row_count": len(output_rows),
        "target_per_dark_category": TARGET_PER_DARK_CATEGORY,
        "counts_before_synthetic": dict(sorted(before_synthetic.items())),
        "synthetic_added_by_category": dict(sorted(synthetic_added.items())),
        "final_counts": dict(sorted(final_counts.items())),
        "policy": {
            "synthetic_review_status": "pending_review",
            "synthetic_split_eligibility": "train_only",
            "original_file_modified": False,
        },
    }
    with SUMMARY.open("w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
