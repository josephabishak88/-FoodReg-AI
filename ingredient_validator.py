import re

from ingredient_normalizer import INGREDIENT_DATABASE


# ---------------------------------------------------------
# COMMON OCR CONFUSIONS
# ---------------------------------------------------------

OCR_DIGIT_FIXES = {
    "O": "0",
    "o": "0",
    "I": "1",
    "i": "1",
    "l": "1",
    "L": "1",
    "S": "5",
    "s": "5",
    "B": "8",
    "b": "8",
}


# ---------------------------------------------------------
# GET VALID INS CODES
# ---------------------------------------------------------

VALID_INS_CODES = set()

for ingredient_data in INGREDIENT_DATABASE.values():

    ins = ingredient_data.get("ins")

    if ins:
        VALID_INS_CODES.add(
            str(ins)
        )


# ---------------------------------------------------------
# EXTRACT POSSIBLE CODE
# ---------------------------------------------------------

def extract_possible_code(text):

    match = re.search(
        r"\b(?:INS\s*|E\s*)([A-Z0-9]{3})\b",
        text
    )

    if not match:
        return None

    return match.group(1)


# ---------------------------------------------------------
# CORRECT OCR CODE
# ---------------------------------------------------------

def correct_ocr_code(raw_code):

    if not raw_code:
        return {
            "raw": raw_code,
            "corrected": None,
            "confidence": 0.0,
            "status": "NO_CODE"
        }

    raw_code = raw_code.strip()

    # Already numeric
    if raw_code.isdigit():

        if raw_code in VALID_INS_CODES:

            return {
                "raw": raw_code,
                "corrected": raw_code,
                "confidence": 1.0,
                "status": "VALID"
            }

        return {
            "raw": raw_code,
            "corrected": raw_code,
            "confidence": 0.5,
            "status": "UNKNOWN_CODE"
        }


    # Try OCR character correction
    corrected = ""

    for char in raw_code:

        corrected += OCR_DIGIT_FIXES.get(
            char,
            char
        )

    # Must become a 3-digit number
    if not corrected.isdigit() or len(corrected) != 3:

        return {
            "raw": raw_code,
            "corrected": None,
            "confidence": 0.0,
            "status": "INVALID"
        }


    # Check against known additive codes
    if corrected in VALID_INS_CODES:

        return {
            "raw": raw_code,
            "corrected": corrected,
            "confidence": 0.95,
            "status": "OCR_CORRECTED"
        }


    return {
        "raw": raw_code,
        "corrected": corrected,
        "confidence": 0.5,
        "status": "UNKNOWN_CODE"
    }


# ---------------------------------------------------------
# VALIDATE INGREDIENT TEXT
# ---------------------------------------------------------

def validate_ingredient_text(text):

    code = extract_possible_code(
        text
    )

    if code is None:

        return {
            "original": text,
            "has_code": False,
            "code": None,
            "confidence": 0.0,
            "status": "NO_CODE"
        }

    result = correct_ocr_code(
        code
    )

    return {
        "original": text,
        "has_code": True,
        "code": result["corrected"],
        "raw_code": result["raw"],
        "confidence": result["confidence"],
        "status": result["status"]
    }