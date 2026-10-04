import streamlit as st
from PIL import Image

st.set_page_config(
    page_title="FoodReg AI Test",
    page_icon="🥫"
)

st.title("🥫 FoodReg AI Test")
st.write("Upload an ingredient-label image.")

uploaded_file = st.file_uploader(
    "Choose an image",
    type=["jpg", "jpeg", "png"]
)

if uploaded_file is not None:
    image = Image.open(uploaded_file)

    st.image(
        image,
        caption="Uploaded Ingredient Label",
        use_container_width=True
    )

    st.success("Image uploaded successfully!")