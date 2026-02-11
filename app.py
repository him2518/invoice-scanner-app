import streamlit as st
import os
import json
import base64
import time
import google.generativeai as genai
from google.cloud import vision
import fitz  # PyMuPDF

# --- PAGE CONFIG ---
st.set_page_config(page_title="Smart Doc Analyzer", page_icon="🧠", layout="wide")

# --- 1. SETUP CREDENTIALS (OCR) ---
if "google_credentials" in st.secrets:
    try:
        encoded_key = st.secrets["google_credentials"]["encoded_key"]
        decoded_key = base64.b64decode(encoded_key).decode("utf-8")
        with open("service_account.json", "w") as f:
            f.write(decoded_key)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
    except Exception as e:
        st.error(f"❌ Error setting up OCR Credentials: {e}")
        st.stop()
elif os.path.exists("service_account.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"

# --- 2. THE EYES (OCR ENGINE) ---
def extract_text_from_file(uploaded_file):
    try:
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
    except Exception as e:
        return f"Error: {e}"

# --- 3. THE BRAIN (GEMINI AI - SELF HEALING) ---
def analyze_with_gemini(text_content):
    # GET KEY FROM SECRETS
    if "gemini_api_key" not in st.secrets:
        return {"error": "Missing 'gemini_api_key' in Streamlit Secrets!"}
    
    api_key = st.secrets["gemini_api_key"]
    genai.configure(api_key=api_key)
    
    # LIST OF MODELS TO TRY (In order of preference)
    # We try newer models first, then fall back to older reliable ones
    model_candidates = [
        'models/gemini-2.0-flash',
        'models/gemini-1.5-flash',
        'models/gemini-pro'
    ]
    
    prompt = f"""
    You are an expert financial document analyzer. Extract data from this text into a JSON object.
    
    Fields for CAR QUOTATION:
    - document_type: "CAR_QUOTATION"
    - ex_showroom, tcs, life_tax, insurance, extended_warranty
    - accessories, fastag, vas, temp_reg, other_charges, on_road_price
    - car_model
    
    Fields for GST INVOICE:
    - document_type: "GST_INVOICE"
    - gstin, account_number, ifsc_code, invoice_date
    - total_amount, cgst_amount, sgst_amount, igst_amount
    
    Rules:
    - Return ONLY valid JSON.
    - If value missing, use 0.0 or null.
    - Convert "1,20,000.00" to 120000.00.
    
    Document Text:
    {text_content}
    """
    
    last_error = ""
    
    for model_name in model_candidates:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(text)
            
        except Exception as e:
            error_str = str(e)
            last_error = error_str
            # If rate limit, wait briefly then try next model
            if "429" in error_str:
                time.sleep(1)
                continue
            # If model not found, try next model immediately
            if "404" in error_str:
                continue
                
    return {"error": f"All models failed. Last error: {last_error}"}

# --- 4. UI LAYOUT ---
st.title("🧠 Smart Document Analyzer")
st.write("Upload a **Car Quotation** or **Invoice**.")

# Sidebar (Only for Razorpay now)
with st.sidebar:
    if "gemini_api_key" in st.secrets:
        st.success(f"✅ Gemini Key Loaded from Secrets")
    else:
        st.error("⚠️ Gemini Key MISSING in Secrets")
        
    st.divider()
    st.header("🔐 Other Keys")
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Secret", type="password")

uploaded_file = st.file_uploader("Upload Document", type=["pdf", "jpg", "png", "jpeg"])

if uploaded_file:
    if st.button("🚀 Analyze Document"):
        with st.spinner("👀 Reading text..."):
            raw_text = extract_text_from_file(uploaded_file)
        
        with st.spinner("🧠 Gemini is thinking..."):
            data = analyze_with_gemini(raw_text)
        
        if "error" in data:
            st.error("Analysis Failed")
            st.code(data['error'])
        else:
            st.success(f"✅ Detected: {data.get('document_type', 'Unknown')}")
            
            if data.get("document_type") == "CAR_QUOTATION":
                c1, c2, c3 = st.columns(3)
                c1.metric("Ex-Showroom", f"₹{data.get('ex_showroom', 0):,}")
                c2.metric("Road Tax", f"₹{data.get('life_tax', 0):,}")
                c3.metric("On-Road Price", f"₹{data.get('on_road_price', 0):,}")
                
                st.subheader("Breakdown")
                st.json(data)
                
            elif data.get("document_type") == "GST_INVOICE":
                c1, c2 = st.columns(2)
                c1.metric("GSTIN", data.get("gstin", "N/A"))
                c2.metric("Total", f"₹{data.get('total_amount', 0):,}")
                st.json(data)
            else:
                st.write(data)
