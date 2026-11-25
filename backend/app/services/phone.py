"""Nigerian phone number validation and E.164 normalization."""

import re

NIGERIAN_PHONE_PATTERN = re.compile(r"^\+234(70|80|81|90|91)\d{8}$")


def normalize_nigerian_phone(raw_phone: str) -> str:
    """Normalize local or international Nigerian mobile numbers to +234XXXXXXXXXX."""
    if not raw_phone:
        raise ValueError("Phone number is required.")

    cleaned = re.sub(r"[\s\-()]+", "", raw_phone.strip())

    if cleaned.startswith("+2340") and len(cleaned) == 14:
        normalized = f"+234{cleaned[5:]}"
    elif cleaned.startswith("+234"):
        normalized = cleaned
    elif cleaned.startswith("2340") and len(cleaned) == 14:
        normalized = f"+234{cleaned[4:]}"
    elif cleaned.startswith("234") and len(cleaned) == 13:
        normalized = f"+{cleaned}"
    elif cleaned.startswith("0") and len(cleaned) == 11:
        normalized = f"+234{cleaned[1:]}"
    elif len(cleaned) == 10 and cleaned[:2] in {"70", "80", "81", "90", "91"}:
        normalized = f"+234{cleaned}"
    else:
        raise ValueError(
            "Enter a valid Nigerian mobile number (e.g. 08012345678 or +2348012345678)."
        )

    if not NIGERIAN_PHONE_PATTERN.match(normalized):
        raise ValueError(
            "Enter a valid Nigerian mobile number with prefix 070, 080, 081, 090, or 091."
        )

    return normalized
