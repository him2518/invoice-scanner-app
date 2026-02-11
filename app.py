import streamlit as st
import os
import json
import base64
import time
import urllib.parse  # Added for Google Search Link
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

# --- 3. THE BRAIN (GEMINI AI) ---
def analyze_with_gemini(text_content):
    # GET KEY FROM SECRETS
    if "gemini_api_key" not in st.secrets:
        return {"error": "Missing 'gemini_api_key' in Streamlit Secrets!"}
    
    api_key = st.secrets["gemini_api_key"]
    genai.configure(api_key=api_key)
    
    # LIST OF MODELS TO TRY
    model_candidates = [
        'models/gemini-2.0-flash',
        'models/gemini-1.5-flash',
        'models/gemini-pro'
    ]
    
    # --- UPDATED PROMPT WITH NEW FIELDS ---
    prompt = f"""
    You are an expert financial auditor. Extract data from this text into a JSON object.
    
    1. **Dealer & Contact Info:**
       - "dealer_name": (Name of showroom/agency)
       - "dealer_address": (Full address)
       - "dealer_phone": (Phone/Mobile)
       - "dealer_email": (Email)
    
    2. **Invoice Details:**
       - "invoice_number", "invoice_date", "customer_name"
    
    3. **Bank Details (For Fraud Check):**
       - "bank_name", "account_number", "ifsc_code"
       - "beneficiary_name" (Name on the bank account - Vital for fraud check)
    
    4. **Terms:**
       - "terms_summary": (Summarize cancellation/refund policy in 1 sentence)

    5. **Financials (Car Quotation):**
       - "document_type": "CAR_QUOTATION"
       - "ex_showroom", "tcs", "life_tax", "insurance", "extended_warranty"
       - "accessories", "fastag", "vas", "temp_reg", "other_charges", "on_road_price"
       - "car_model", "customer_state"
    
    6. **Financials (GST Invoice):**
       - "document_type": "GST_INVOICE"
       - "gstin", "total_amount", "cgst_amount", "sgst_amount", "igst_amount"
    
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
            if "429" in error_str:
                time.sleep(1)
                continue
            if "404" in error_str:
                continue
                
    return {"error": f"All models failed. Last error: {last_error}"}

# --- 4. NEW AUDITOR LOGIC ---
def audit_quotation(data):
    """Checks for overpricing and fraud indicators."""
    warnings = []
    trust_score = 100
    
    # 1. Handling Charges Check
    other = data.get('other_charges', 0)
    if other > 1500:
        warnings.append(f"🚩 **High Handling Charges:** ₹{other}. Ask for waiver.")
        trust_score -= 20

    # 2. Insurance Markup Check
    ex_price = data.get('ex_showroom', 0)
    ins = data.get('insurance', 0)
    if ex_price > 0:
        ratio = (ins / ex_price) * 100
        if ratio > 5.0:
            warnings.append(f"🚩 **Expensive Insurance:** {ratio:.1f}% of car value (Standard is 3-4%).")
            trust_score -= 15

    # 3. TCS Rule Check
    tcs = data.get('tcs', 0)
    if ex_price < 990000 and tcs > 0:
        warnings.append(f"🚩 **TCS Error:** Tax charged on car < ₹10 Lakhs.")
        trust_score -= 10
        
    # 4. Beneficiary Check (Fraud)
    dealer = str(data.get('dealer_name', '')).lower()
    beneficiary = str(data.get('beneficiary_name', '')).lower()
    if len(dealer) > 3 and len(beneficiary) > 3:
        if dealer[:4] not in beneficiary and beneficiary[:4] not in dealer:
            warnings.append(f"🚨 **Name Mismatch:** Dealer is '{data['dealer_name']}' but Bank Account is '{data['beneficiary_name']}'. Verify!")
            trust_score -= 30

    return warnings, max(0, trust_score)

# --- 5. UI LAYOUT ---
st.title("🧠 Smart Document Analyzer & Auditor")
st.write("Upload a **Car Quotation** or **Invoice**.")

with st.sidebar:
    if "gemini_api_key" in st.secrets:
        st.success(f"✅ Gemini Key Loaded")
    else:
        st.error("⚠️ Gemini Key MISSING")
        
    st.divider()
    st.header("🔐 Other Keys")
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Secret", type="password")

uploaded_file = st.file_uploader("Upload Document", type=["pdf", "jpg", "png", "jpeg"])

if uploaded_file:
    if st.button("🚀 Analyze & Audit"):
        with st.spinner("👀 Reading text..."):
            raw_text = extract_text_from_file(uploaded_file)
        
        with st.spinner("🧠 AI is analyzing & auditing..."):
            data = analyze_with_gemini(raw_text)
        
        if "error" in data:
            st.error("Analysis Failed")
            st.code(data['error'])
        else:
            # --- DISPLAY AUDITOR RESULTS FIRST
