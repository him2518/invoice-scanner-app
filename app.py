import streamlit as st
import os
import re
import requests
import base64
import json
import difflib

# --- CONFIGURATION ---
st.set_page_config(page_title="Super Scanner (Invoice + Car)", page_icon="🚗", layout="wide")

# --- 1. SETUP GOOGLE CREDENTIALS (BASE64 METHOD) ---
if "google_credentials" in st.secrets:
    try:
        encoded_key = st.secrets["google_credentials"]["encoded_key"]
        decoded_key = base64.b64decode(encoded_key).decode("utf-8")
        
        with open("service_account.json", "w") as f:
            f.write(decoded_key)
            
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
        
    except Exception as e:
        st.error(f"❌ Error decoding key: {e}")
        st.stop()
elif os.path.exists("service_account.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
else:
    st.error("❌ Critical: Google Credentials not found. Please add them to Streamlit Secrets.")
    st.stop()

# --- 2. IMPORT LIBRARIES SAFELY ---
try:
    from google.cloud import vision
    import fitz  # PyMuPDF
except ImportError as e:
    st.error(f"❌ Missing Library: {e}")
    st.stop()

# --- 3. OCR ENGINE (THE EYES) ---
def get_text_from_file(uploaded_file):
    client = vision.ImageAnnotatorClient()
    content = uploaded_file.getvalue()
    image = None

    if uploaded_file.type == "application/pdf":
        doc = fitz.open(stream=content, filetype="pdf")
        page = doc.load_page(0)
        pix = page.get_pixmap()
        img_bytes = pix.tobytes("png")
        image = vision.Image(content=img_bytes)
    else:
        image = vision.Image(content=content)
    
    # DOCUMENT_TEXT_DETECTION is best for tables & handwriting
    response = client.document_text_detection(image=image)
    return response.full_text_annotation.text

# --- 4. VERIFICATION ENGINE (THE TRUTH) ---
def verify_gst_razorpay(gstin, api_key, api_secret):
    url = f"https://api.razorpay.com/v1/gst/gstin/{gstin}"
    try:
        response = requests.get(url, auth=(api_key, api_secret))
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def
