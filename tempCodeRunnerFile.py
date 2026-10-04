import streamlit as st
from paddleocr import PaddleOCR
from PIL import Image
import numpy as np
import re
from ingredient_normalizer import normalize_ingredient
# --------------------------------------------------
# PAGE CONFIGURATION
# --------------------------------------------------

st.set_page_config(
    page_title="FoodReg AI",
    page_icon="🥫",
    layout="wide"
)

st.title("🥫 FoodReg AI")
st.subheader("AI Food Ingredient Regulatory Checker")

st.write(
    "Upload a food ingredient label. "
    "The system will read and extract the ingredients."
)


# --------------------------------------------------
# INGREDIENT DATABASE
# --------------------------------------------------
# Initial mapping of common INS / E-numbers.
# We will expand this later using proper regulatory data.

ADDITIVE_MAP = {

    "330": "Citric Acid",
    "211": "Sodium Benzoate",
    "202": "Potassium Sorbate",
    "200": "Sorbic Acid",
    "220": "Sulfur Dioxide",
    "221": "Sodium Sulfite",
    "223": "Sodium Metabisulfite",
    "224": "Potassium Metabisulfite",

    "102": "Tartrazine",
    "110": "Sunset Yellow FCF",
    "122": "Carmoisine",
    "124": "Ponceau 4R",
    "129": "Allura Red AC",

    "320": "BHA",
    "321": "BHT",

    "322": "Lecithin",
    "415": "Xanthan Gum",
    "412": "Guar Gum",
    "407": "Carrageenan",

    "621": "Monosodium Glutamate",
    "627": "Disodium Guanylate",
    "631": "Disodium Inosinate",

    "950": "Acesulfame Potassium",
    "951": "Aspartame",
    "952": "Cyclamate",
    "955": "Sucralose",
    "960": "Steviol Glycosides"
}


# --------------------------------------------------
# NORMALIZE INS / E NUMBERS
# --------------------------------------------------

def normalize_additive(code):

    code = code.upper().strip()

    # Remove E prefix
    if code.startswith("E"):
        number = code[1:]

    # Remove INS prefix
    elif code.startswith("INS"):
        number = code[3:].strip()

    else:
        number = code

    if number in ADDITIVE_MAP:

        return {
            "code": number,
            "name": ADDITIVE_MAP[number]
        }

    return {
        "code": number,
        "name": "Unknown additive"
    }


# --------------------------------------------------
# EXTRACT ADDITIVE CODES
# --------------------------------------------------

def extract_additive_codes(text):

    found = []

    # Match:
    # INS 330
    # INS330
    # E330
    # E 330

    pattern = r"\b(?:INS\s*|E\s*)(\d{3})\b"

    matches = re.findall(pattern, text.upper())

    for number in matches:

        result = normalize_additive(number)

        if result not in found:
            found.append(result)

    # Also catch standalone 3-digit additive numbers
    # when they appear inside brackets.
    bracket_numbers = re.findall(
        r"\(\s*(\d{3})\s*\)",
        text
    )

    for number in bracket_numbers:

        result = normalize_additive(number)

        if result not in found:
            found.append(result)

    return found


# --------------------------------------------------
# CLEAN OCR TEXT
# --------------------------------------------------

def clean_text(text):

    text = text.replace("\n", " ")

    # Remove repeated spaces
    text = re.sub(r"\s+", " ", text)

    # Normalize punctuation
    text = text.replace(";", ",")

    return text.strip()


# --------------------------------------------------
# EXTRACT INGREDIENTS
# --------------------------------------------------

def extract_ingredients(text):

    text = clean_text(text)

    # Remove common headings
    text = re.sub(
        r"\b(INGREDIENTS?|COMPOSITION|CONTAINS)\s*:?",
        "",
        text,
        flags=re.IGNORECASE
    )

    # Split by commas
    parts = re.split(r",", text)

    ingredients = []

    for part in parts:

        part = part.strip()

        if not part:
            continue

        # Remove unnecessary brackets
        part = part.strip(" .:-")

        if len(part) < 2:
            continue

        ingredients.append(part)

    return ingredients


# --------------------------------------------------
# STREAMLIT UPLOAD
# --------------------------------------------------

uploaded_file = st.file_uploader(
    "📸 Upload ingredient label",
    type=["jpg", "jpeg", "png"]
)


if uploaded_file is not None:

    # --------------------------------------------------
    # LOAD IMAGE
    # --------------------------------------------------

    image = Image.open(uploaded_file).convert("RGB")

    image_np = np.array(image)

    col1, col2 = st.columns(2)

    with col1:

        st.image(
            image,
            caption="Uploaded Ingredient Label",
            use_container_width=True
        )


    # --------------------------------------------------
    # OCR
    # --------------------------------------------------

    with st.spinner("🔍 Reading ingredient label..."):

        ocr = PaddleOCR(
            lang="en"
        )

        result = ocr.predict(image_np)


    # --------------------------------------------------
    # EXTRACT OCR TEXT
    # --------------------------------------------------

    detected_text = []

    for res in result:

        if hasattr(res, "json"):

            data = res.json

            if callable(data):
                data = data()

            if isinstance(data, dict):

                ocr_data = data.get("res", data)

                texts = ocr_data.get(
                    "rec_texts",
                    []
                )

                for text in texts:

                    if text.strip():

                        detected_text.append(
                            text.strip()
                        )


    # --------------------------------------------------
    # DISPLAY RAW OCR
    # --------------------------------------------------

    with col2:

        st.subheader("🔤 OCR Text")

        if detected_text:

            raw_text = "\n".join(
                detected_text
            )

            st.text_area(
                "Detected text",
                raw_text,
                height=250
            )

        else:

            st.warning(
                "No text detected. "
                "Try a clearer image."
            )


    # --------------------------------------------------
    # PROCESS OCR
    # --------------------------------------------------

    if detected_text:

        full_text = " ".join(
            detected_text
        )

        # Clean text
        cleaned_text = clean_text(
            full_text
        )

        st.divider()

        st.subheader(
            "🧠 Extracted Ingredients"
        )

        ingredients = extract_ingredients(
            cleaned_text
        )

        # Display ingredients

        for i, ingredient in enumerate(
            ingredients,
            start=1
        ):

            st.write(
                f"**{i}.** {ingredient}"
            )


        # --------------------------------------------------
        # ADDITIVE DETECTION
        # --------------------------------------------------

        st.divider()

        st.subheader(
            "🧪 Detected Food Additives"
        )

        additives = extract_additive_codes(
            cleaned_text
        )

        if additives:

            for additive in additives:

                code = additive["code"]
                name = additive["name"]

                st.write(
                    f"🔹 **INS {code}** → {name}"
                )

        else:

            st.info(
                "No INS/E-number additives detected."
            )