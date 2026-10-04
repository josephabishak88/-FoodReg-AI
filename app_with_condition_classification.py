import re

from urllib.parse import urlparse


import cv2

import numpy as np

import streamlit as st

from PIL import Image

from paddleocr import PaddleOCR


from ingredient_normalizer import INGREDIENT_DATABASE, normalize_ingredient

from regulatory_database import check_ingredient


# =========================================================

# PAGE CONFIGURATION

# =========================================================


st.set_page_config(

    page_title="FoodReg AI",

    page_icon="🥫",

    layout="wide",

)


# =========================================================

# CUSTOM CSS

# =========================================================


st.markdown(

    """

    <style>

    .main-title {

        font-size: 42px;

        font-weight: 700;

        margin-bottom: 0;

    }


    .subtitle {

        font-size: 18px;

        color: #666666;

        margin-bottom: 25px;

    }


    .section-title {

        font-size: 24px;

        font-weight: 650;

        margin-top: 20px;

        margin-bottom: 12px;

    }


    .ingredient-card {

        padding: 14px 16px;

        border-radius: 12px;

        border: 1px solid #e5e7eb;

        margin-bottom: 10px;

        background-color: #fafafa;

    }


    .ingredient-name {

        font-size: 17px;

        font-weight: 600;

    }


    .ingredient-code {

        color: #666666;

        font-size: 14px;

    }


    .info-box {

        padding: 15px;

        border-radius: 12px;

        background-color: #f6f8fa;

        border: 1px solid #e5e7eb;

    }

    </style>

    """,

    unsafe_allow_html=True,

)


# =========================================================

# HEADER

# =========================================================


st.markdown(

    '<div class="main-title">🥫 FoodReg AI</div>',

    unsafe_allow_html=True,

)


st.markdown(

    '<div class="subtitle">'

    "Upload an ingredient label to identify ingredients and "

    "compare available regulatory information across countries."

    "</div>",

    unsafe_allow_html=True,

)


# =========================================================

# OCR MODEL

# =========================================================


@st.cache_resource

def load_ocr():

    return PaddleOCR(

        lang="en",

        enable_mkldnn=False,

        device="cpu",

    )


# =========================================================

# IMAGE PREPROCESSING

# =========================================================


def preprocess_image(image_np: np.ndarray) -> np.ndarray:

    image = image_np.copy()


    height, width = image.shape[:2]

    min_width = 1400


    if width < min_width:

        scale = min_width / width

        new_width = int(width * scale)

        new_height = int(height * scale)


        image = cv2.resize(

            image,

            (new_width, new_height),

            interpolation=cv2.INTER_CUBIC,

        )


    gray = cv2.cvtColor(

        image,

        cv2.COLOR_RGB2GRAY,

    )


    clahe = cv2.createCLAHE(

        clipLimit=2.0,

        tileGridSize=(8, 8),

    )


    enhanced = clahe.apply(gray)


    enhanced = cv2.GaussianBlur(

        enhanced,

        (3, 3),

        0,

    )


    return enhanced


# =========================================================

# TEXT HELPERS

# =========================================================


def clean_text(text: str) -> str:

    text = text.replace("\n", " ")

    text = text.replace("\r", " ")

    text = text.replace(";", ",")


    text = re.sub(

        r"\s+",

        " ",

        text,

    )


    return text.strip()


# =========================================================

# INGREDIENT SECTION EXTRACTION

# =========================================================


def extract_ingredient_section(

    detected_text: list[str],

) -> str:

    """

    Find the ingredient heading and return only the

    ingredient section.


    We never fall back to the complete OCR text because

    nutrition facts, licence information and storage text

    must not become ingredients.

    """


    joined = clean_text(

        " ".join(detected_text)

    )


    heading_pattern = re.compile(

        r"\b(?:other\s+)?"

        r"(?:ingredients?|ngredients?|ngredent|composition)"

        r"\s*:?\s*",

        flags=re.IGNORECASE,

    )


    heading = heading_pattern.search(

        joined

    )


    if not heading:

        return ""


    section = joined[

        heading.end():

    ]


    # -----------------------------------------------------

    # STOP AT NON-INGREDIENT CONTENT

    # -----------------------------------------------------


    stop_pattern = re.compile(

        r"\b(?:"

        r"contains"

        r"|may\s+contain"

        r"|best\s+before"

        r"|use\s+before"

        r"|licen[cs]e"

        r"|lic\s*\.?\s*no"

        r"|store\s+in"

        r"|storage"

        r"|nutritional?"

        r"|nutrition\s+information"

        r"|manufactured\s+by"

        r"|marketed\s+by"

        r"|customer\s+care"

        r"|mrp"

        r"|net\s*(?:weight|wt)"

        r"|batch\s*(?:no|number)?"

        r"|packed\s+by"

        r")\b",

        flags=re.IGNORECASE,

    )


    stop = stop_pattern.search(

        section

    )


    if stop:

        section = section[

            :stop.start()

        ]


    # -----------------------------------------------------

    # REMOVE SUBSECTION HEADINGS

    # -----------------------------------------------------


    section = re.sub(

        r"\b(?:"

        r"noodle"

        r"|noodles"

        r"|masala\s+tastemaker"

        r"|tastemaker"

        r"|seasoning"

        r")\s*:\s*",

        "",

        section,

        flags=re.IGNORECASE,

    )


    return clean_text(

        section

    )


# =========================================================

# INGREDIENT OCR CLEANUP

# =========================================================


ORDINARY_OCR_REPLACEMENTS = {

    r"\bwheat\s+fur\b": "Wheat Flour",

    r"\bwheat\s+flur\b": "Wheat Flour",

    r"\bwheat\s+flor\b": "Wheat Flour",


    r"\bedible\s+vegetable\s+ol\b":

        "Edible Vegetable Oil",


    r"\bedible\s+vegetable\s+0il\b":

        "Edible Vegetable Oil",


    r"\bedible\s+vegetable\s*$":

        "Edible Vegetable Oil",


    r"\bsal\b":

        "Salt",


    r"\bcalum\b":

        "calcium",


    r"\bcalcuim\b":

        "calcium",


    r"\bcalicium\b":

        "calcium",


    r"\bcabnate\b":

        "carbonate",


    r"\bcarbnate\b":

        "carbonate",


    r"\bgluen\b":

        "gluten",


    r"\bprotien\b":

        "protein",


    r"\bpotasium\b":

        "potassium",


    r"\bchlorde\b":

        "chloride",


    r"\bcloride\b":

        "chloride",


    r"\bspces\b":

        "spices",


    r"\bwhch\b":

        "which",


    r"\bblad\s+pepper\b":

        "black pepper",


    r"\bblak\s+pepper\b":

        "black pepper",


    r"\bhydrolysd\b":

        "hydrolysed",

    r"\bsuga\b":

        "sugar",


    r"\btumeric\b":

        "turmeric",

}


def clean_ordinary_ingredient_text(

    text: str,

) -> str:


    cleaned = clean_text(text)


    for pattern, replacement in (

        ORDINARY_OCR_REPLACEMENTS.items()

    ):

        cleaned = re.sub(

            pattern,

            replacement,

            cleaned,

            flags=re.IGNORECASE,

        )


    return cleaned


# =========================================================

# SPLIT KNOWN COMBINED INGREDIENT PHRASES

# =========================================================


def split_known_compound_ingredients(

    ingredients: list[str],

) -> list[str]:


    result = []


    for ingredient in ingredients:


        text = clean_ordinary_ingredient_text(

            ingredient

        )


        # -------------------------------------------------
        # OCR LABELLED ADDITIVES
        # -------------------------------------------------

        # Acidity regulator (330) / OCR: Ad Ae (330)
        if re.search(
            r"(?:acidity\s*regulator|ad\s*ae)\s*\(?\s*330\s*\)?",
            text,
            flags=re.IGNORECASE,
        ):
            result.append("Citric Acid")
            continue

        # Mineral (Potassium Chloride)
        if re.fullmatch(
            r"mineral\s*\(\s*potassium\s+chloride\s*\)",
            text,
            flags=re.IGNORECASE,
        ):
            result.append("Potassium Chloride")
            continue

        # Flavour enhancer (635) and raising agent (500(i))
        # Handles OCR forms such as 500( or 500().
        if re.search(
            r"(?:flavou?r\s+)?enhancer\s*\(?\s*635\s*\)?"
            r".*?(?:and|,)?.*?raising\s+agent\s*\(?\s*500"
            r"\s*(?:\(\s*[a-z]\s*\))?\s*\)?",
            text,
            flags=re.IGNORECASE,
        ):
            result.extend(
                [
                    "Disodium 5'-Ribonucleotides",
                    "Sodium Carbonate",
                ]
            )
            continue

        # Colour (150D)
        if re.fullmatch(
            r"colou?r\s*\(\s*150\s*d\s*\)",
            text,
            flags=re.IGNORECASE,
        ):
            result.append("Caramel IV")
            continue

        # -------------------------------------------------

        # Mineral Calcium Carbonate + Guar Gum

        # -------------------------------------------------


        if re.fullmatch(

            r"mineral\s+calcium\s+carbonate\s+and\s+guar\s+gum",

            text,

            flags=re.IGNORECASE,

        ):


            result.extend(

                [

                    "Mineral Calcium Carbonate",

                    "Guar Gum",

                ]

            )


            continue


        # -------------------------------------------------

        # Period between ingredients

        # -------------------------------------------------


        text = re.sub(

            r"\.\s+",

            ", ",

            text,

        )


        # -------------------------------------------------

        # Sugar + Edible Starch

        # -------------------------------------------------


        if re.fullmatch(

            r"sugar\s+edible\s+starch",

            text,

            flags=re.IGNORECASE,

        ):


            result.extend(

                [

                    "Sugar",

                    "Edible Starch",

                ]

            )


            continue


        # -------------------------------------------------

        # Compound phrase with trailing ingredient

        # -------------------------------------------------


        # -------------------------------------------------
        # Enhancer 635 + 500
        # -------------------------------------------------

        if re.fullmatch(
            r"enhancer\s+635\s+and\s+500",
            text,
            flags=re.IGNORECASE,
        ):
            result.extend(
                [
                    "Disodium 5'-Ribonucleotides",
                    "Sodium Carbonate",
                ]
            )
            continue

        match = re.fullmatch(

            r"mineral\s+calcium\s+carbonate\s+and\s+guar\s+gum\s*,?\s*(.+)",

            text,

            flags=re.IGNORECASE,

        )


        if match:


            result.extend(

                [

                    "Mineral Calcium Carbonate",

                    "Guar Gum",

                    match.group(1).strip(),

                ]

            )


            continue


        result.append(

            text

        )


    return result


# =========================================================

# SMART INGREDIENT EXTRACTION

# =========================================================


def extract_ingredients(

    text: str,

) -> list[str]:


    text = clean_text(

        text

    )


    # Remove remaining heading.

    text = re.sub(

        r"\b(?:"

        r"ingredients?"

        r"|ngredients?"

        r"|ngredent"

        r"|composition"

        r")\s*:?\s*",

        "",

        text,

        flags=re.IGNORECASE,

    )


    # Remove subsection labels.

    text = re.sub(

        r"\b(?:"

        r"noodle"

        r"|noodles"

        r"|masala\s+tastemaker"

        r"|tastemaker"

        r"|seasoning"

        r")\s*:\s*",

        "",

        text,

        flags=re.IGNORECASE,

    )


    # Fix:

    # Guar Gum. Hydrolysed Groundnut Protein

    #

    # without breaking:

    # 23.6%

    text = re.sub(

        r"(?<=[A-Za-z])\.\s+(?=[A-Za-z])",

        ", ",

        text,

    )


    text = text.replace(

        ";",

        ",",

    )


    ingredients = []

    current = []


    round_depth = 0

    square_depth = 0

    curly_depth = 0


    for char in text:


        if char == "(":

            round_depth += 1


        elif char == "[":

            square_depth += 1


        elif char == "{":

            curly_depth += 1


        elif char == ")":

            round_depth = max(

                0,

                round_depth - 1,

            )


        elif char == "]":

            square_depth = max(

                0,

                square_depth - 1,

            )


        elif char == "}":

            curly_depth = max(

                0,

                curly_depth - 1,

            )


        is_top_level_comma = (

            char == ","

            and round_depth == 0

            and square_depth == 0

            and curly_depth == 0

        )


        if is_top_level_comma:


            ingredient = "".join(

                current

            ).strip(

                " .:-"

            )


            if len(ingredient) >= 2:


                ingredients.append(

                    ingredient

                )


            current = []


        else:


            current.append(

                char

            )


    ingredient = "".join(

        current

    ).strip(

        " .:-"

    )


    if len(ingredient) >= 2:


        ingredients.append(

            ingredient

        )


    # Split known combined phrases.

    ingredients = (

        split_known_compound_ingredients(

            ingredients

        )

    )


    # -----------------------------------------------------

    # CLEAN + DEDUPLICATE

    # -----------------------------------------------------


    cleaned = []

    seen = set()


    for ingredient in ingredients:


        ingredient = (

            clean_ordinary_ingredient_text(

                ingredient

            )

        )


        ingredient = re.sub(

            r"\s+",

            " ",

            ingredient,

        ).strip(

            " .:-"

        )


        if len(ingredient) < 2:

            continue


        key = ingredient.lower()


        if key in seen:

            continue


        seen.add(

            key

        )


        cleaned.append(

            ingredient

        )


    return cleaned


# =========================================================

# OCR CODE VALIDATION

# =========================================================


OCR_CODE_FIXES = {

    "O": "0",

    "o": "0",

    "I": "1",

    "i": "1",

    "L": "1",

    "l": "1",

    "S": "5",

    "s": "5",

    "B": "8",

    "b": "8",

}


def get_valid_ins_codes() -> set[str]:


    codes = set()


    for data in INGREDIENT_DATABASE.values():


        ins = data.get(

            "ins"

        )


        if ins:


            codes.add(

                str(ins)

            )


    return codes


def validate_ingredient_code(

    text: str,

) -> dict:


    pattern = (

        r"\b(?:INS\s*|E\s*)"

        r"([A-Z0-9]{3})\b"

    )


    match = re.search(

        pattern,

        text,

        flags=re.IGNORECASE,

    )


    if not match:


        return {

            "original": text,

            "corrected_text": text,

            "has_code": False,

            "raw_code": None,

            "corrected_code": None,

            "confidence": 0.0,

            "status": "NO_CODE",

        }


    raw_code = match.group(

        1

    )


    normalized_raw = raw_code.upper()


    valid_codes = get_valid_ins_codes()


    if normalized_raw.isdigit():


        if normalized_raw in valid_codes:


            return {

                "original": text,

                "corrected_text": text,

                "has_code": True,

                "raw_code": raw_code,

                "corrected_code": normalized_raw,

                "confidence": 1.0,

                "status": "VALID",

            }


        return {

            "original": text,

            "corrected_text": text,

            "has_code": True,

            "raw_code": raw_code,

            "corrected_code": normalized_raw,

            "confidence": 0.5,

            "status": "UNKNOWN_CODE",

        }


    corrected = "".join(

        OCR_CODE_FIXES.get(

            char,

            char,

        )

        for char in raw_code

    )


    if (

        len(corrected) == 3

        and corrected.isdigit()

        and corrected in valid_codes

    ):


        start, end = match.span(

            1

        )


        corrected_text = (

            text[:start]

            + corrected

            + text[end:]

        )


        return {

            "original": text,

            "corrected_text": corrected_text,

            "has_code": True,

            "raw_code": raw_code,

            "corrected_code": corrected,

            "confidence": 0.95,

            "status": "OCR_CORRECTED",

        }


    return {

        "original": text,

        "corrected_text": text,

        "has_code": True,

        "raw_code": raw_code,

        "corrected_code": corrected,

        "confidence": 0.5,

        "status": "UNKNOWN_CODE",

    }


# =========================================================

# OCR SINGLE PASS

# =========================================================


def run_single_ocr(

    ocr,

    image,

) -> list[str]:


    detected_text = []


    try:


        results = ocr.predict(

            image

        )


    except Exception:


        return []


    for result in results:


        try:


            data = result.json


            if callable(data):

                data = data()


            if not isinstance(

                data,

                dict,

            ):

                continue


            ocr_data = data.get(

                "res",

                data,

            )


            texts = ocr_data.get(

                "rec_texts",

                [],

            )


            scores = ocr_data.get(

                "rec_scores",

                [],

            )


            if not isinstance(

                texts,

                list,

            ):

                continue


            for index, text in enumerate(

                texts

            ):


                if text is None:

                    continue


                text = str(

                    text

                ).strip()


                if not text:

                    continue


                if (

                    isinstance(

                        scores,

                        list,

                    )

                    and index < len(scores)

                ):


                    try:


                        score = float(

                            scores[index]

                        )


                        if score < 0.45:

                            continue


                    except (

                        ValueError,

                        TypeError,

                    ):

                        pass


                detected_text.append(

                    text

                )


        except Exception:


            continue


    return detected_text


# =========================================================

# OCR

# =========================================================


def run_ocr(

    image_np: np.ndarray,

) -> list[str]:


    ocr = load_ocr()


    enhanced_image = preprocess_image(

        image_np

    )


    original_results = run_single_ocr(

        ocr,

        image_np,

    )


    enhanced_results = run_single_ocr(

        ocr,

        enhanced_image,

    )


    all_results = (

        original_results

        + enhanced_results

    )


    unique_text = []


    seen = set()


    for text in all_results:


        key = re.sub(

            r"\s+",

            " ",

            text.lower(),

        ).strip()


        if key in seen:

            continue


        seen.add(

            key

        )


        unique_text.append(

            text

        )


    return unique_text


# =========================================================

# DISPLAY HELPERS

# =========================================================


def get_status_display(

    status: str,

) -> str:


    status_map = {

        "NOT_AUTHORISED":

            "🔴 Not authorised",

        "BANNED":

            "🔴 Prohibited",

        "RESTRICTED":

            "🟠 Restricted",

        "CHECK_CONDITIONS":

            "🟡 Conditions apply",

        "CHECK":

            "🟡 Requires verification",

        "AUTHORISED":

            "🟢 Authorised",

        "LISTED":

            "🟢 Listed",

        "REGULATED":

            "🟢 Regulated",

        "IDENTIFIED":

            "ℹ️ Identified",

    }


    return status_map.get(

        status,

        "⚪ Unknown",

    )


def classify_condition(status: str, restriction: str, label: str) -> dict:
    """
    Convert the source wording into a clear, user-facing condition type.

    This is a display classification only. It does not create a new
    regulatory conclusion beyond what is present in the database record.
    """

    status = (status or "UNKNOWN").upper().strip()
    text = f"{restriction} {label}".lower()

    if status in {"BANNED", "NOT_AUTHORISED"}:
        return {
            "type": "Prohibited / not authorised",
            "explanation": "The current record says the ingredient is prohibited or not authorised in this jurisdiction.",
        }

    if status == "RESTRICTED":
        if any(term in text for term in [
            "food categor",
            "schedule",
            "maximum",
            "limit",
            "level",
            "regulation",
            "cfr",
        ]):
            return {
                "type": "Restricted use",
                "explanation": "Use is restricted by the conditions described in the source record.",
            }
        return {
            "type": "Restricted use",
            "explanation": "The current regulatory record identifies restricted use.",
        }

    if status == "CHECK":
        return {
            "type": "Verification required",
            "explanation": "The database record requires additional verification before drawing a use conclusion.",
        }

    if "quantum satis" in text or "quantum" in text:
        base = "Quantum satis / food-category specific"
        explanation = "Use is permitted only under the applicable food-category conditions; quantum satis means no numerical maximum is specified in that entry, subject to the cited rules."
        if "gmp" in text:
            base = "Quantum satis + GMP"
            explanation += " GMP conditions also apply where stated."
        return {"type": base, "explanation": explanation}

    if "gmp" in text or "good manufacturing practice" in text:
        if any(term in text for term in [
            "food categor",
            "schedule",
            "regulation",
            "cfr",
            "maximum",
            "level",
            "limit",
        ]):
            return {
                "type": "GMP + specific use conditions",
                "explanation": "The source requires good manufacturing practice plus the listed food-category, schedule, level, or regulatory conditions.",
            }
        return {
            "type": "GMP",
            "explanation": "Use is subject to good manufacturing practice as stated by the source.",
        }

    if any(term in text for term in [
        "maximum level",
        "maximum",
        "mg/kg",
        "limit",
        "level",
    ]):
        return {
            "type": "Maximum level / limit",
            "explanation": "The source sets or references a maximum permitted level or other quantitative limit.",
        }

    if any(term in text for term in [
        "food categor",
        "category-specific",
        "category specific",
        "footnote",
        "schedule",
    ]):
        return {
            "type": "Food-category specific",
            "explanation": "The permitted use depends on the food category, schedule, or footnotes cited by the source.",
        }

    if any(term in text for term in [
        "21 cfr",
        "regulation",
        "regulations",
        "applicable cfr",
    ]):
        return {
            "type": "Specific regulation",
            "explanation": "Use is subject to the regulation or CFR provision cited by the source.",
        }

    if status in {"AUTHORISED", "LISTED", "REGULATED", "CHECK_CONDITIONS"}:
        return {
            "type": "Conditions apply",
            "explanation": "The ingredient is covered by the source, but the source record contains conditions that must be followed.",
        }

    return {
        "type": "No specific condition classified",
        "explanation": "See the source wording for the applicable requirements.",
    }


def is_valid_url(

    url: str,

) -> bool:


    try:


        parsed = urlparse(

            url

        )


        return (

            parsed.scheme in {

                "http",

                "https",

            }

            and bool(

                parsed.netloc

            )

        )


    except Exception:


        return False


# =========================================================

# NORMALIZATION

# =========================================================


def normalize_results(

    ingredients: list[str],

) -> list[dict]:


    results = []

    seen = set()


    for ingredient in ingredients:


        validation = (

            validate_ingredient_code(

                ingredient

            )

        )


        corrected_text = validation[

            "corrected_text"

        ]


        normalized_text = (

            clean_ordinary_ingredient_text(

                corrected_text

            )

        )


        try:


            result = normalize_ingredient(

                normalized_text

            )


        except Exception as exc:


            result = {

                "original": ingredient,

                "canonical": normalized_text,

                "ins": None,

                "method": "normalization error",

                "confidence": 0.0,

                "error": str(exc),

            }


        result["original"] = ingredient


        result["ocr_text"] = (

            corrected_text

        )


        result["text_correction"] = {

            "original": corrected_text,

            "corrected_text": normalized_text,

            "changed": (

                corrected_text.lower()

                != normalized_text.lower()

            ),

        }


        result["validation"] = (

            validation

        )


        canonical = str(

            result.get(

                "canonical",

                normalized_text,

            )

        ).strip()


        if not canonical:

            continue


        key = canonical.lower()


        if key in seen:

            continue


        seen.add(

            key

        )

        results.append(

            result

        )


    return results


# =========================================================

# UPLOAD SECTION

# =========================================================


st.markdown(

    '<div class="section-title">'

    "📸 Upload Product Label"

    "</div>",

    unsafe_allow_html=True,

)


st.write(

    "Upload a clear photo of the ingredient list printed "

    "on your food package."

)


uploaded_file = st.file_uploader(

    "Choose an image",

    type=[

        "jpg",

        "jpeg",

        "png",

    ],

    label_visibility="collapsed",

)


# =========================================================

# NO IMAGE

# =========================================================


if uploaded_file is None:


    st.info(

        "Start by uploading a clear ingredient-label photo. "

        "Avoid glare, extreme blur, or very small text."

    )


    st.stop()


# =========================================================

# LOAD IMAGE

# =========================================================


try:


    image = Image.open(

        uploaded_file

    ).convert(

        "RGB"

    )


except Exception as exc:


    st.error(

        f"Could not open the image: {exc}"

    )


    st.stop()


image_np = np.array(

    image

)


# =========================================================

# PREVIEW

# =========================================================


st.divider()


col1, col2 = st.columns(

    [1, 1]

)


with col1:


    st.subheader(

        "📷 Product Image"

    )


    st.image(

        image,

        use_container_width=True,

    )


with col2:


    st.subheader(

        "🔍 Ready to Analyze"

    )


    st.markdown(

        """

        <div class="info-box">

        FoodReg AI will read the label, isolate the ingredient

        section, correct common OCR mistakes, standardize

        ingredient names, and check the regulatory records

        currently available in the project database.

        </div>

        """,

        unsafe_allow_html=True,

    )


    st.write("")


    analyze = st.button(

        "🔎 Analyze Ingredients",

        use_container_width=True,

        type="primary",

    )


# =========================================================

# ANALYSIS

# =========================================================


if analyze:


    # -----------------------------------------------------

    # OCR

    # -----------------------------------------------------


    with st.spinner(

        "Reading and analyzing the ingredient label..."

    ):


        try:


            detected_text = run_ocr(

                image_np

            )


        except Exception as exc:


            st.error(

                f"Unable to read the image: {exc}"

            )


            st.stop()


    if not detected_text:


        st.warning(

            "No readable text was found. "

            "Try a clearer, closer photo with good lighting."

        )


        st.stop()


    # -----------------------------------------------------

    # CLEAN OCR

    # -----------------------------------------------------


    full_text = " ".join(

        detected_text

    )


    cleaned_text = clean_text(

        full_text

    )


    # -----------------------------------------------------

    # EXTRACT INGREDIENT SECTION

    # -----------------------------------------------------


    ingredient_section = (

        extract_ingredient_section(

            detected_text

        )

    )


    if not ingredient_section:


        st.warning(

            "The ingredient section could not be detected. "

            "The app will not use the full OCR text as ingredients."

        )


        st.stop()


    # -----------------------------------------------------

    # EXTRACT INGREDIENTS

    # -----------------------------------------------------


    ingredients = extract_ingredients(

        ingredient_section

    )


    if not ingredients:


        st.warning(

            "The ingredient section was found, but no "

            "ingredient entries could be separated."

        )


        st.stop()


    # -----------------------------------------------------

    # NORMALIZATION

    # -----------------------------------------------------


    normalized_results = normalize_results(

        ingredients

    )


    # =====================================================

    # SUMMARY

    # =====================================================


    st.divider()


    st.markdown(

        '<div class="section-title">'

        "🧾 Ingredient Analysis"

        "</div>",

        unsafe_allow_html=True,

    )


    total_count = len(

        normalized_results

    )


    additive_count = sum(

        1

        for item in normalized_results

        if item.get("ins")

    )


    correction_count = sum(

        1

        for item in normalized_results

        if (

            item.get(

                "validation",

                {},

            ).get("status")

            == "OCR_CORRECTED"

            or item.get(

                "text_correction",

                {},

            ).get("changed")

        )

    )


    regulatory_count = 0

    flagged_count = 0


    regulatory_results = []


    # =====================================================

    # REGULATORY LOOKUP

    # =====================================================


    for item in normalized_results:


        canonical = str(

            item.get(

                "canonical",

                "",

            )

        ).strip()


        if not canonical:

            continue


        record = check_ingredient(

            canonical

        )


        regulatory_results.append(

            {

                "ingredient": canonical,

                "record": record,

            }

        )


        if record.get("found"):


            regulatory_count += 1


            for country_data in record.get(

                "jurisdictions",

                {},

            ).values():


                if is_flagged_status(

                    country_data.get(

                        "status",

                        "",

                    )

                ):


                    flagged_count += 1


    # =====================================================

    # METRICS

    # =====================================================


    c1, c2, c3, c4, c5 = st.columns(

        5

    )


    with c1:

        st.metric(

            "Ingredients",

            total_count,

        )


    with c2:

        st.metric(

            "Additives",

            additive_count,

        )


    with c3:

        st.metric(

            "OCR corrections",

            correction_count,

        )


    with c4:

        st.metric(

            "Regulatory records",

            regulatory_count,

        )


    with c5:

        st.metric(

            "Restrictions found",

            flagged_count,

        )


    # =====================================================

    # OCR CORRECTION WARNINGS

    # =====================================================


    for item in normalized_results:


        validation = item.get(

            "validation",

            {},

        )


        text_correction = item.get(

            "text_correction",

            {},

        )


        if validation.get(

            "status"

        ) == "OCR_CORRECTED":


            st.warning(

                f"⚠️ Additive OCR correction: "

                f"{validation.get('raw_code')} → "

                f"{validation.get('corrected_code')}"

            )


        elif text_correction.get(

            "changed"

        ):


            st.info(

                f"ℹ️ Ingredient OCR cleanup: "

                f"'{text_correction.get('original')}' → "

                f"'{text_correction.get('corrected_text')}'"

            )


    # =====================================================

    # UNKNOWN ADDITIVE CODES

    # =====================================================


    for item in normalized_results:


        validation = item.get(

            "validation",

            {},

        )


        if validation.get(

            "status"

        ) == "UNKNOWN_CODE":


            st.info(

                f"ℹ️ Additive code "

                f"'{validation.get('raw_code')}' was detected, "

                f"but it is not currently mapped in our database."

            )


    # =====================================================

    # INGREDIENT LIST

    # =====================================================


    st.markdown(

        '<div class="section-title">'

        "🧪 Identified Ingredients"

        "</div>",

        unsafe_allow_html=True,

    )


    for item in normalized_results:

        canonical = str(
            item.get(
                "canonical",
                "",
            )
        ).strip()

        ins = item.get("ins")

        if not canonical:
            continue

        display_name = canonical.title()

        with st.container(border=True):

            if ins:
                st.markdown(f"**🧪 {display_name}**")
                st.caption(f"INS {ins}")
            else:
                st.markdown(f"**🥣 {display_name}**")


    # =====================================================

    # REGULATORY RESULTS

    # =====================================================


    st.divider()


    st.markdown(

        '<div class="section-title">'

        "🌍 International Regulatory Check"

        "</div>",

        unsafe_allow_html=True,

    )


    st.caption(

        "A missing record means the ingredient is not yet "

        "covered by the project's current regulatory database. "

        "It does not mean the ingredient is automatically "

        "safe, approved, or unrestricted."

    )


    # -----------------------------------------------------
    # COMPACT COUNTRY COMPARISON TABLE
    # -----------------------------------------------------

    st.markdown("### 🌍 Country Comparison Summary")
    st.caption(
        "This table summarizes the regulatory records currently verified in the project database. "
        "A missing record means the country is not yet covered here; it does not mean the ingredient is banned or dangerous."
    )

    with st.expander("ℹ️ What the condition types mean"):
        st.markdown(
            "- **GMP** — use must follow good manufacturing practice.  "
            "\n- **Food-category specific** — the rule depends on the food category.  "
            "\n- **Maximum level / limit** — the source specifies a quantitative limit.  "
            "\n- **Specific regulation** — the source points to a named regulation/CFR provision.  "
            "\n- **Quantum satis** — no numerical maximum is stated in that entry, but use still follows the applicable conditions.  "
            "\n- **Prohibited / not authorised** — the current source record explicitly gives that status.  "
            "\n- **Verification required** — the current record is not sufficient for a direct use conclusion."
        )

    for summary_item in regulatory_results:
        summary_ingredient = summary_item["ingredient"]
        summary_record = summary_item["record"]
        summary_rows = []

        if summary_record.get("found"):
            for summary_country, summary_data in summary_record.get("jurisdictions", {}).items():
                summary_status = summary_data.get("status", "UNKNOWN")
                summary_label = summary_data.get("label", "No regulatory summary available")
                summary_condition = summary_data.get("restriction", "")
                condition_info = classify_condition(
                    summary_status,
                    summary_condition,
                    summary_label,
                )
                summary_rows.append({
                    "Country / jurisdiction": summary_country,
                    "Status": get_status_display(summary_status),
                    "Condition type": condition_info["type"],
                    "What it means": condition_info["explanation"],
                    "Source summary": summary_label,
                })
        else:
            summary_rows.append({
                "Country / jurisdiction": "Current database coverage",
                "Status": "⚪ No verified record",
                "Condition type": "No verified record",
                "What it means": "This ingredient is not yet covered by a verified record in the project database.",
                "Source summary": "Do not interpret missing coverage as approval, prohibition, or danger.",
            })

        st.markdown(f"**🧪 {summary_ingredient.title()}**")
        st.table(summary_rows)

    st.divider()


    for item in regulatory_results:


        ingredient = item[

            "ingredient"

        ]


        record = item[

            "record"

        ]


        if not record.get(

            "found"

        ):


            st.info(

                f"No regulatory record is currently available "

                f"for **{ingredient.title()}**."

            )


            continue


        heading = (

            f"🧪 {ingredient.title()}"

        )


        if record.get("ins"):


            heading += (

                f" — INS {record['ins']}"

            )


        st.subheader(

            heading

        )


        jurisdictions = record.get(

            "jurisdictions",

            {},

        )


        for country, data in jurisdictions.items():


            status = data.get(

                "status",

                "UNKNOWN",

            )


            label = data.get(

                "label",

                "Status unavailable",

            )


            restriction = data.get(

                "restriction",

                "",

            )


            reason = data.get(

                "reason",

                "",

            )


            authority = data.get(

                "authority",

                "",

            )


            source = data.get(

                "source",

                "",

            )


            verified = data.get(

                "verified",

                "",

            )


            display_status = (

                get_status_display(

                    status

                )

            )


            with st.container(

                border=True

            ):


                st.markdown(

                    f"**🌍 {country}**"

                )


                st.write(

                    f"**Status:** "

                    f"{display_status}"

                )


                # One short plain-English line based directly on the
                # regulatory source summary stored in the database.
                if label:
                    st.info(
                        f"**Source summary:** {label}"
                    )

                if restriction:
                    st.caption(
                        f"**Condition:** {restriction}"
                    )

                if reason:
                    with st.expander("Regulatory basis"):
                        st.write(reason)


                if authority:


                    st.write(

                        f"**Authority:** "

                        f"{authority}"

                    )


                if verified:


                    st.caption(

                        f"Last verified: {verified}"

                    )


                if is_valid_url(

                    source

                ):


                    st.markdown(

                        f"[🔗 View official source]({source})"

                    )


        st.divider()


    # =====================================================

    # TECHNICAL DETAILS

    # =====================================================


    with st.expander(

        "⚙️ View technical details"

    ):


        st.write(

            "Raw OCR text:"

        )


        st.text_area(

            "OCR output",

            full_text,

            height=180,

            key="raw_ocr_output",

        )


        st.write(

            "Detected ingredient section:"

        )


        st.text_area(

            "Ingredient section",

            ingredient_section,

            height=180,

            key="ingredient_section_output",

        )


        st.write(

            "Parsed ingredient entries:"

        )


        st.text_area(

            "Parsed ingredients",

            "\n".join(ingredients),

            height=180,

            key="parsed_ingredients_output",

        )


        st.write(

            "Normalization details:"

        )


        for item in normalized_results:


            validation = item.get(

                "validation",

                {},

            )


            text_correction = item.get(

                "text_correction",

                {},

            )


            st.write(

                f"**{item.get('original', '')}** → "

                f"{item.get('canonical', '')} "

                f"| Additive: "

                f"{validation.get('status', 'NO_CODE')} "

                f"| Text changed: "

                f"{text_correction.get('changed', False)}"

            )


    st.success(

        "Analysis complete. Regulatory findings are based "

        "only on records currently present in the FoodReg AI database."

    )