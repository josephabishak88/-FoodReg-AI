"""
Conservative OCR cleanup for ordinary food-ingredient names.
"""

import re
from typing import Any

from rapidfuzz import fuzz, process


# =========================================================
# EXACT OCR ALIASES
# =========================================================

EXACT_OCR_ALIASES = {

    # Flour
    "fur": "flour",
    "flur": "flour",
    "flor": "flour",
    "f1our": "flour",

    # Calcium
    "calum": "calcium",
    "calcuim": "calcium",
    "calicium": "calcium",
    "caliium": "calcium",

    # Sugar
    "suga": "sugar",
    "suger": "sugar",
    "suggar": "sugar",

    # Vegetable
    "vegtbl": "vegetable",
    "vegetabe": "vegetable",
    "vegetab1e": "vegetable",

    # Oil
    "0il": "oil",
    "ol": "oil",

    # Starch
    "stach": "starch",
    "sta rch": "starch",

    # Powder
    "powdr": "powder",

    # Flavour
    "flavr": "flavour",

    # Hydrolysed
    "hydrolysd": "hydrolysed",
    "hydrolyzed": "hydrolysed",

    # Protein
    "protien": "protein",

    # Gluten
    "gluen": "gluten",

    # Mineral
    "minral": "mineral",

    # Potassium
    "potasium": "potassium",
    "potasssium": "potassium",

    # Carbonate
    "carbnate": "carbonate",
    "cabnate": "carbonate",

    # Chloride
    "chlorde": "chloride",
    "cloride": "chloride",

    # Spices
    "spces": "spices",

    # Onion
    "onon": "onion",

    # Garlic
    "garic": "garlic",

    # Tomato
    "tomatoe": "tomato",

    # Salt
    "sal": "salt",
}


# =========================================================
# COMMON WORD VOCABULARY
# =========================================================

COMMON_WORDS = sorted(
    {
        "acid",
        "alginic",
        "almond",
        "ammonium",
        "anti",
        "antioxidant",
        "apple",
        "arrowroot",
        "ascorbic",
        "barley",
        "basil",
        "beetroot",
        "benzoate",
        "bicarbonate",
        "butter",
        "cacao",
        "caffeine",
        "calcium",
        "carbonate",
        "caramel",
        "carrot",
        "cashew",
        "cellulose",
        "chickpea",
        "chilli",
        "chloride",
        "citric",
        "cocoa",
        "coconut",
        "corn",
        "cornflour",
        "cornstarch",
        "cream",
        "curcumin",
        "dextrose",
        "edible",
        "flavour",
        "flavor",
        "flour",
        "fructose",
        "garlic",
        "ginger",
        "glucose",
        "gluten",
        "glycerol",
        "guar",
        "gum",
        "groundnut",
        "hydrolysed",
        "lecithin",
        "lemon",
        "maltodextrin",
        "malt",
        "maize",
        "mango",
        "milk",
        "mineral",
        "modified",
        "monosodium",
        "mustard",
        "natural",
        "nitrite",
        "nitrate",
        "oats",
        "oil",
        "onion",
        "paprika",
        "pea",
        "peanut",
        "pectin",
        "potassium",
        "protein",
        "rice",
        "salt",
        "sodium",
        "soy",
        "soya",
        "spice",
        "spices",
        "stabiliser",
        "stabilizer",
        "starch",
        "sucrose",
        "sugar",
        "sunflower",
        "tapioca",
        "tomato",
        "turmeric",
        "vegetable",
        "vitamin",
        "water",
        "wheat",
        "xanthan",
        "yeast",
    }
)


# =========================================================
# PHRASE ALIASES
# =========================================================

PHRASE_ALIASES = {

    "wheat flo ur":
        "wheat flour",

    "wheat fl our":
        "wheat flour",

    "wheat fur":
        "wheat flour",

    "edible vegetable ol":
        "edible vegetable oil",

    "edible vegetable 0il":
        "edible vegetable oil",

    "edible vegetable oil":
        "edible vegetable oil",

    "mineral calum carbonate":
        "mineral calcium carbonate",

    "mineral cabnate":
        "mineral carbonate",

    "potassium ch1oride":
        "potassium chloride",

    "wheat gluen":
        "wheat gluten",

    "mixed spces":
        "mixed spices",
}


# =========================================================
# SPECIAL PHRASE FIXES
# =========================================================

def apply_special_phrase_fixes(
    text: str,
) -> str:

    working = text

    # -----------------------------------------
    # Flour
    # -----------------------------------------

    working = re.sub(
        r"\bwheat\s+fur\b",
        "Wheat Flour",
        working,
        flags=re.IGNORECASE,
    )

    # -----------------------------------------
    # Vegetable Oil
    # -----------------------------------------

    working = re.sub(
        r"\bedible\s+vegetable\s+ol\b",
        "Edible Vegetable Oil",
        working,
        flags=re.IGNORECASE,
    )

    working = re.sub(
        r"\bedible\s+vegetable\s*$",
        "Edible Vegetable Oil",
        working,
        flags=re.IGNORECASE,
    )

    # -----------------------------------------
    # Salt
    # -----------------------------------------

    working = re.sub(
        r"\bsal\b",
        "Salt",
        working,
        flags=re.IGNORECASE,
    )

    # -----------------------------------------
    # Sugar + Edible Starch
    # -----------------------------------------

    working = re.sub(
        r"\bsugar\s+edible\s+starch\b",
        "Sugar, Edible Starch",
        working,
        flags=re.IGNORECASE,
    )

    # -----------------------------------------
    # Mineral Calcium Carbonate + Guar Gum
    # -----------------------------------------

    working = re.sub(
        r"\bmineral\s+calcium\s+carbonate\s+and\s+guar\s+gum\b",
        "Mineral Calcium Carbonate, Guar Gum",
        working,
        flags=re.IGNORECASE,
    )

    # -----------------------------------------
    # Hydrolysed Groundnut Protein
    # -----------------------------------------

    working = re.sub(
        r"\bguar\s+gum\.\s*hydrolysed\s+groundnut\s+protein\b",
        "Guar Gum, Hydrolysed Groundnut Protein",
        working,
        flags=re.IGNORECASE,
    )

    # -----------------------------------------
    # Enhancer codes
    # -----------------------------------------

    working = re.sub(
        r"\benhancer\s+635\s+and\s+500\b",
        "Enhancer 635, Enhancer 500",
        working,
        flags=re.IGNORECASE,
    )

    return working


# =========================================================
# WORD CORRECTION
# =========================================================

def _word_correction(
    word: str,
) -> tuple[str, float]:

    lower = word.lower()

    if lower in EXACT_OCR_ALIASES:

        return (
            EXACT_OCR_ALIASES[lower],
            1.0,
        )

    if (
        len(lower) < 4
        or lower in COMMON_WORDS
    ):

        return (
            word,
            0.0,
        )

    match = process.extractOne(
        lower,
        COMMON_WORDS,
        scorer=fuzz.ratio,
        score_cutoff=92,
    )

    if not match:

        return (
            word,
            0.0,
        )

    candidate, score, _ = match

    if candidate == lower:

        return (
            word,
            0.0,
        )

    return (
        candidate,
        round(
            score / 100.0,
            3,
        ),
    )


# =========================================================
# MAIN NORMALIZER
# =========================================================

def normalize_ingredient_text(
    text: str,
) -> dict[str, Any]:

    original = re.sub(
        r"\s+",
        " ",
        str(text),
    ).strip()

    working = original.lower()

    # -----------------------------------------
    # Phrase-level fixes
    # -----------------------------------------

    for bad, good in sorted(
        PHRASE_ALIASES.items(),
        key=lambda x: len(x[0]),
        reverse=True,
    ):

        working = working.replace(
            bad,
            good,
        )

    # -----------------------------------------
    # Special ingredient fixes
    # -----------------------------------------

    working = apply_special_phrase_fixes(
        working
    )

    # -----------------------------------------
    # Token correction
    # -----------------------------------------

    tokens = working.split()

    corrected_tokens = []

    corrections = []

    for token in tokens:

        m = re.match(
            r"^(\W*)([\w'-]+)(\W*)$",
            token,
        )

        if not m:

            corrected_tokens.append(
                token
            )

            continue

        prefix, core, suffix = m.groups()

        corrected, confidence = (
            _word_correction(
                core
            )
        )

        if (
            corrected.lower()
            != core.lower()
        ):

            corrections.append(
                {
                    "from": core,
                    "to": corrected,
                    "confidence": confidence,
                }
            )

        corrected_tokens.append(
            prefix
            + corrected
            + suffix
        )

    corrected_text = re.sub(
        r"\s+",
        " ",
        " ".join(
            corrected_tokens
        ),
    ).strip()

    return {
        "original": original,
        "corrected_text": corrected_text,
        "changed": (
            corrected_text.lower()
            != original.lower()
        ),
        "corrections": corrections,
    }