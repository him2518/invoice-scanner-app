import streamlit as st
import os
import re
import requests
import base64
import json
import difflib

# --- CONFIGURATION ---
st.set_page_config(page_title="Super Scanner (Invoice + Car)", page_icon="🚗", layout="wide")

# --- 1. SETUP GOOGLE CREDENTIALS ---
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

# --- 3. OCR ENGINE ---
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
    
    response = client.document_text_detection(image=image)
    return response.full_text_annotation.text

# --- 4. VERIFICATION ENGINE ---
def verify_gst_razorpay(gstin, api_key, api_secret):
    url = f"https://api.razorpay.com/v1/gst/gstin/{gstin}"
    try:
        response = requests.get(url, auth=(api_key, api_secret))
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def verify_bank_razorpay(account, ifsc, api_key, api_secret):
    url = "https://api.razorpay.com/v1/fund_accounts/validation"
    data = {
        "account_number": account,
        "fund_account": {
            "account_type": "bank_account",
            "bank_account": {
                "name": "Merchant",
                "ifsc": ifsc,
                "account_number": account
            }
        },
        "amount": 100, 
        "currency": "INR"
    }
    try:
        response = requests.post(url, json=data, auth=(api_key, api_secret))
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- 5. PARSING LOGIC ---
def smart_parse_car_quotation(text):
    data = {}
    
    context_map = {
        'ex_showroom': ["Ex-Showroom", "Basic Price", "Unit Cost", "Vehicle Cost", "Showroom Price"],
        'tcs': ["TCS", "Tax Collected", "Income Tax", "1% Tax", "Tax @1%"],
        'life_tax': ["Life Tax", "Road Tax", "RTO", "Perm Registration", "Regn Charges", "Perm Reg"],
        'fastag': ["Fastag", "Fast Tag", "Tag Cost", "RFID"],
        'temp_reg': ["Temp", "Temporary", "TR Charges", "Tmp Reg"],
        
        'insurance': ["Insurance", "Comprehensive", "OD Premium", "Bumper to Bumper", "Zero Dep"],
        'extended_warranty': ["Extended Warranty", "Ext Warranty", "EW", "Shield", "T Secure", "Protection Plan"],
        'rsa': ["RSA", "Roadside", "Assistance"],
        
        'accessories': ["Accessories", "Kit", "Fitting", "Acc.", "Mud Flap", "Mats"],
        'vas': ["VAS", "Value Added", "Coating", "Teflon", "Anti Rust", "Smiles"],
        'others': ["Others", "Misc", "Handling", "Logistics", "Depot Charges", "H.C."],
        
        'on_road': ["On Road", "Total", "Net Amount", "Grand Total", "Final Price", "To Pay"]
    }

    def extract_value_smart(field_key):
        keywords = context_map.get(field_key, [])
        # Look across newlines (up to 80 chars)
        pattern = rf"(?:{'|'.join(keywords)})[\s\S]{{0,80}}?([\d,]+\.\d{{2}})"
        
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_val = match.group(1).replace(",", "")
            try:
                return float(raw_val)
            except:
                return 0.0
        return 0.0

    for key in context_map:
        data[key] = extract_value_smart(key)

    return data

def parse_gst_invoice(text):
    data = {"type": "GST_INVOICE"}
    
    gst_match = re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-
