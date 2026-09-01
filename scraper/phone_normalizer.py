"""
phone_normalizer.py
-------------------
Converts raw phone number strings to E.164 format using Google's libphonenumber.
Used by both the scraper and the n8n Code node equivalent.
"""

import phonenumbers
from phonenumbers import NumberParseException, PhoneNumberFormat

# Maps ISO 2-letter country codes to default region for libphonenumber
COUNTRY_TO_REGION: dict[str, str] = {
    "IN": "IN",  # +91
    "AE": "AE",  # +971
    "QA": "QA",  # +974
    "SA": "SA",  # +966
    "SG": "SG",  # +65
}


def normalize_e164(raw_number: str, country_code: str = "IN") -> str | None:
    """
    Normalize a raw phone number string to E.164 format.

    Args:
        raw_number: The raw phone number string (may contain spaces, dashes, etc.)
        country_code: ISO 2-letter country code (e.g. "IN", "AE"). Used to infer
                      the country dial code when the raw number has no country prefix.

    Returns:
        E.164 formatted string (e.g. "+919876543210") or None if invalid/unparseable.
    """
    if not raw_number:
        return None

    region = COUNTRY_TO_REGION.get(country_code.upper(), "IN")

    # Clean the number: remove common non-numeric chars except + and leading digits
    cleaned = raw_number.strip()

    try:
        parsed = phonenumbers.parse(cleaned, region)
        if phonenumbers.is_valid_number(parsed):
            return phonenumbers.format_number(parsed, PhoneNumberFormat.E164)
        return None
    except NumberParseException:
        return None


def e164_to_wa_link(e164_number: str) -> str | None:
    """
    Convert an E.164 number to a WhatsApp wa.me link (strips the leading +).

    Args:
        e164_number: E.164 formatted number, e.g. "+919876543210"

    Returns:
        WhatsApp link base, e.g. "919876543210" (to be used as wa.me/919876543210)
    """
    if not e164_number or not e164_number.startswith("+"):
        return None
    return e164_number[1:]  # Strip the leading '+'


if __name__ == "__main__":
    # Quick sanity tests
    test_cases = [
        ("9876543210", "IN"),
        ("+91 98765 43210", "IN"),
        ("050-123-4567", "AE"),
        ("+971501234567", "AE"),
        ("33123456", "QA"),
        ("0512345678", "SA"),
        ("91234567", "SG"),
    ]
    for raw, country in test_cases:
        result = normalize_e164(raw, country)
        print(f"  [{country}] {raw!r:25} → {result}")
