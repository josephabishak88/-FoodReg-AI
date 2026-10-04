
import re
from rapidfuzz import process, fuzz


# =========================================================
# INGREDIENT / ADDITIVE DATABASE
# =========================================================

INGREDIENT_DATABASE = {

    "sodium benzoate": {
        "ins": "211",
        "aliases": [
            "sodium benzoate",
            "benzoate",
            "e211",
            "ins 211",
        ],
    },

    "citric acid": {
        "ins": "330",
        "aliases": [
            "citric acid",
            "citric",
            "e330",
            "ins 330",
        ],
    },

    "potassium sorbate": {
        "ins": "202",
        "aliases": [
            "potassium sorbate",
            "e202",
            "ins 202",
        ],
    },

    "tartrazine": {
        "ins": "102",
        "aliases": [
            "tartrazine",
            "e102",
            "ins 102",
        ],
    },

    "sunset yellow fcf": {
        "ins": "110",
        "aliases": [
            "sunset yellow",
            "sunset yellow fcf",
            "e110",
            "ins 110",
        ],
    },

    "carmoisine": {
        "ins": "122",
        "aliases": [
            "carmoisine",
            "azorubine",
            "e122",
            "ins 122",
        ],
    },

    "ponceau 4r": {
        "ins": "124",
        "aliases": [
            "ponceau 4r",
            "ponceau 4-r",
            "e124",
            "ins 124",
        ],
    },

    "allura red ac": {
        "ins": "129",
        "aliases": [
            "allura red",
            "allura red ac",
            "e129",
            "ins 129",
        ],
    },

    "bha": {
        "ins": "320",
        "aliases": [
            "bha",
            "butylated hydroxyanisole",
            "e320",
            "ins 320",
        ],
    },

    "bht": {
        "ins": "321",
        "aliases": [
            "bht",
            "butylated hydroxytoluene",
            "e321",
            "ins 321",
        ],
    },

    "lecithin": {
        "ins": "322",
        "aliases": [
            "lecithin",
            "soy lecithin",
            "soya lecithin",
            "e322",
            "ins 322",
        ],
    },

    "xanthan gum": {
        "ins": "415",
        "aliases": [
            "xanthan gum",
            "xanthan",
            "e415",
            "ins 415",
        ],
    },

    "guar gum": {
        "ins": "412",
        "aliases": [
            "guar gum",
            "guar",
            "e412",
            "ins 412",
        ],
    },

    "carrageenan": {
        "ins": "407",
        "aliases": [
            "carrageenan",
            "e407",
            "ins 407",
        ],
    },

    "monosodium glutamate": {
        "ins": "621",
        "aliases": [
            "monosodium glutamate",
            "msg",
            "e621",
            "ins 621",
        ],
    },

    "disodium guanylate": {
        "ins": "627",
        "aliases": [
            "disodium guanylate",
            "guanylate",
            "e627",
            "ins 627",
        ],
    },

    "disodium inosinate": {
        "ins": "631",
        "aliases": [
            "disodium inosinate",
            "inosinate",
            "e631",
            "ins 631",
        ],
    },

    "disodium 5'-ribonucleotides": {
        "ins": "635",
        "aliases": [
            "disodium 5'-ribonucleotides",
            "disodium 5 ribonucleotides",
            "disodium ribonucleotides",
            "ribonucleotides",
            "enhancer 635",
            "e635",
            "ins 635",
        ],
    },

    "acesulfame potassium": {
        "ins": "950",
        "aliases": [
            "acesulfame potassium",
            "acesulfame k",
            "acesulfame-k",
            "e950",
            "ins 950",
        ],
    },

    "aspartame": {
        "ins": "951",
        "aliases": [
            "aspartame",
            "e951",
            "ins 951",
        ],
    },

    "sucralose": {
        "ins": "955",
        "aliases": [
            "sucralose",
            "e955",
            "ins 955",
        ],
    },

    "steviol glycosides": {
        "ins": "960",
        "aliases": [
            "steviol glycosides",
            "steviol glycoside",
            "stevia extract",
            "stevia",
            "e960",
            "ins 960",
        ],
    },

    "calcium carbonate": {
        "ins": "170",
        "aliases": [
            "calcium carbonate",
            "calcium carbonate mineral",
            "mineral calcium carbonate",
            "e170",
            "ins 170",
        ],
    },

    "potassium chloride": {
        "ins": "508",
        "aliases": [
            "potassium chloride",
            "potassium chlorides",
            "e508",
            "ins 508",
        ],
    },

    "sodium carbonate": {
        "ins": "500",
        "aliases": [
            "sodium carbonate",
            "sodium carbonates",
            "sodium carbonate salts",
            "enhancer 500",
            "e500",
            "e500(i)",
            "ins 500",
            "ins 500(i)",
        ],
    },

    "amaranth": {
        "ins": "123",
        "aliases": [
            "amaranth",
            "e123",
            "ins 123",
        ],
    },

    # Caramel IV / Class IV
    "caramel iv": {
        "ins": "150d",
        "aliases": [
            "caramel iv",
            "caramel 150d",
            "caramel class iv",
            "class iv caramel",
            "e150d",
            "ins 150d",
        ],
    },
}


# =========================================================
# BUILD ALIAS LOOKUP
# =========================================================

ALIAS_LOOKUP = {}

for canonical_name, data in INGREDIENT_DATABASE.items():

    ALIAS_LOOKUP[canonical_name.lower()] = canonical_name

    for alias in data.get("aliases", []):
        ALIAS_LOOKUP[alias.lower()] = canonical_name


# =========================================================
# CLEAN TEXT
# =========================================================

def clean_ingredient_text(text: str) -> str:

    if not text:
        return ""

    text = str(text).strip()

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    text = text.replace(
        "–",
        "-",
    )

    text = text.replace(
        "—",
        "-",
    )

    text = re.sub(
        r"\s*,\s*",
        ", ",
        text,
    )

    return text.strip(
        " .,;:-"
    )


# =========================================================
# REMOVE COMMON DESCRIPTORS
# =========================================================

def remove_descriptors(text: str) -> str:

    text = text.strip()

    patterns = [
        r"\bhydrolysed\b",
        r"\bhydrolyzed\b",
        r"\bgroundnut\b",
        r"\bpeanut\b",
        r"\bprotein\b",
        r"\bflavour\b",
        r"\bflavor\b",
        r"\bpowder\b",
        r"\bfood\s+conditioner\b",
    ]

    for pattern in patterns:

        text = re.sub(
            pattern,
            " ",
            text,
            flags=re.IGNORECASE,
        )

    text = re.sub(
        r"\s+",
        " ",
        text,
    )

    return text.strip(
        " .,;:-"
    )


# =========================================================
# NORMALIZE INS / E CODE
# =========================================================

def normalize_code(code: str) -> str | None:

    if not code:
        return None

    code = str(
        code
    ).strip().upper()

    # Remove INS / E prefix
    code = re.sub(
        r"^(?:INS|E)\s*",
        "",
        code,
        flags=re.IGNORECASE,
    )

    # Supports:
    # 330
    # 412
    # 150D
    match = re.search(
        r"\d{3}[A-Z]?",
        code,
        flags=re.IGNORECASE,
    )

    if not match:
        return None

    return match.group(
        0
    ).lower()


# =========================================================
# FIND INGREDIENT BY CODE
# =========================================================

def find_by_code(code: str):

    normalized_code = normalize_code(
        code
    )

    if not normalized_code:
        return None

    for canonical, data in INGREDIENT_DATABASE.items():

        ingredient_code = normalize_code(
            data.get("ins")
        )

        if ingredient_code == normalized_code:
            return canonical

    return None


# =========================================================
# FIND EXACT ALIAS
# =========================================================

def find_exact(text: str):

    key = text.lower().strip()

    return ALIAS_LOOKUP.get(
        key
    )


# =========================================================
# NORMALIZE INGREDIENT
# =========================================================

def normalize_ingredient(text: str) -> dict:

    original = text

    text = clean_ingredient_text(
        text
    )

    if not text:

        return {
            "original": original,
            "canonical": "",
            "ins": None,
            "method": "empty",
            "confidence": 0.0,
        }

    # -----------------------------------------------------
    # LOOK FOR INS / E CODE
    # -----------------------------------------------------

    code_match = re.search(
        r"\b(?:INS|E)\s*([0-9]{3}[A-Za-z]?)\b",
        text,
        flags=re.IGNORECASE,
    )

    if code_match:

        raw_code = code_match.group(
            1
        )

        canonical = find_by_code(
            raw_code
        )

        if canonical:

            return {
                "original": original,
                "canonical": canonical,
                "ins": INGREDIENT_DATABASE[
                    canonical
                ].get("ins"),
                "method": "INS/E-code",
                "confidence": 1.0,
            }

    # -----------------------------------------------------
    # REMOVE CODE FROM TEXT
    # -----------------------------------------------------

    cleaned = re.sub(
        r"\b(?:INS|E)\s*[0-9]{3}[A-Za-z]?\b",
        "",
        text,
        flags=re.IGNORECASE,
    )

    cleaned = clean_ingredient_text(
        cleaned
    )

    # -----------------------------------------------------
    # EXACT MATCH
    # -----------------------------------------------------

    exact = find_exact(
        cleaned
    )

    if exact:

        return {
            "original": original,
            "canonical": exact,
            "ins": INGREDIENT_DATABASE[
                exact
            ].get("ins"),
            "method": "exact",
            "confidence": 1.0,
        }

    # -----------------------------------------------------
    # SIMPLE DESCRIPTOR CLEANUP
    # -----------------------------------------------------

    descriptor_cleaned = remove_descriptors(
        cleaned
    )

    exact = find_exact(
        descriptor_cleaned
    )

    if exact:

        return {
            "original": original,
            "canonical": exact,
            "ins": INGREDIENT_DATABASE[
                exact
            ].get("ins"),
            "method": "descriptor-cleanup",
            "confidence": 0.95,
        }

    # -----------------------------------------------------
    # SPECIAL OCR FIXES
    # -----------------------------------------------------

    special_fixes = {

        "mineral calcium carbonate":
            "calcium carbonate",

        "enhancer 635":
            "disodium 5'-ribonucleotides",

        "enhancer 500":
            "sodium carbonate",

        "potassium chlorides":
            "potassium chloride",

        "sodium carbonates":
            "sodium carbonate",

        "colour caramel iv":
            "caramel iv",

        "color caramel iv":
            "caramel iv",

    }

    special_key = cleaned.lower()

    if special_key in special_fixes:

        canonical = special_fixes[
            special_key
        ]

        return {
            "original": original,
            "canonical": canonical,
            "ins": INGREDIENT_DATABASE[
                canonical
            ].get("ins"),
            "method": "special-fix",
            "confidence": 0.98,
        }

    # -----------------------------------------------------
    # FUZZY MATCH
    # -----------------------------------------------------

    choices = list(
        ALIAS_LOOKUP.keys()
    )

    if choices:

        match = process.extractOne(
            cleaned.lower(),
            choices,
            scorer=fuzz.token_set_ratio,
        )

        if match:

            matched_alias, score, _ = match

            if score >= 90:

                canonical = ALIAS_LOOKUP[
                    matched_alias
                ]

                return {
                    "original": original,
                    "canonical": canonical,
                    "ins": INGREDIENT_DATABASE[
                        canonical
                    ].get("ins"),
                    "method": "fuzzy",
                    "confidence": round(
                        score / 100,
                        3,
                    ),
                }

    # -----------------------------------------------------
    # UNKNOWN INGREDIENT
    # -----------------------------------------------------

    return {
        "original": original,
        "canonical": cleaned.lower(),
        "ins": None,
        "method": "unknown",
        "confidence": 0.0,
    }


# =========================================================
# OPTIONAL TEST
# =========================================================

if __name__ == "__main__":

    tests = [

        "INS 330",

        "INS 412",

        "INS 170",

        "INS 508",

        "INS 500",

        "INS 635",

        "INS 150D",

        "E150D",

        "Enhancer 635",

        "Enhancer 500",

        "Citric Acid",

        "Guar Gum",

        "Calcium Carbonate",

        "Potassium Chloride",

        "Sodium Carbonate",

        "Caramel IV",

    ]

    for test in tests:

        print(
            f"{test} -> "
            f"{normalize_ingredient(test)}"
        )
