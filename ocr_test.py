import streamlit as st
from paddleocr import PaddleOCR
from PIL import Image
import numpy as np

st.set_page_config(
    page_title="FoodReg AI OCR",
    page_icon="🥫",
    layout="wide"
)

st.title("🥫 FoodReg AI")
st.subheader("Ingredient Label OCR")

uploaded_file = st.file_uploader(
    "📸 Upload an ingredient-label image",
    type=["jpg", "jpeg", "png"]
)

@st.cache_resource
def load_ocr():
    return PaddleOCR(
        lang="en",
        enable_mkldnn=False
    )


if uploaded_file is not None:

    # -----------------------------
    # Load uploaded image
    # -----------------------------
    image = Image.open(uploaded_file).convert("RGB")
    image_np = np.array(image)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("📸 Uploaded Image")

        st.image(
            image,
            use_container_width=True
        )

    # -----------------------------
    # Load OCR model
    # -----------------------------
    ocr = load_ocr()

    # -----------------------------
    # Run OCR
    # -----------------------------
    with st.spinner("🔍 Reading ingredient label..."):

        try:
            results = ocr.predict(image_np)

            detected_text = []

            for result in results:

                data = result.json

                if callable(data):
                    data = data()

                if isinstance(data, dict):

                    ocr_data = data.get(
                        "res",
                        data
                    )

                    texts = ocr_data.get(
                        "rec_texts",
                        []
                    )

                    for text in texts:

                        if text and text.strip():
                            detected_text.append(
                                text.strip()
                            )

        except Exception as e:

            st.error(f"OCR error: {e}")
            st.stop()

    # -----------------------------
    # Display OCR result
    # -----------------------------
    with col2:

        st.subheader("🔤 Detected Text")

        if detected_text:

            for i, text in enumerate(
                detected_text,
                start=1
            ):

                st.write(
                    f"**{i}.** {text}"
                )

            st.divider()

            full_text = " ".join(
                detected_text
            )

            st.subheader("📄 Combined Text")

            st.text_area(
                "OCR Output",
                full_text,
                height=250
            )

        else:

            st.warning(
                "No text detected. "
                "Try a clearer and closer image."
            )