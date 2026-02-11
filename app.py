import streamlit as st
import os
import json
import base64
import time
import urllib.parse
import google.generativeai as genai
from google.cloud import vision
import fitz  # PyMuPDF

# --- PAGE CONFIG ---
st.set_page_config(page_title="Auto-Auditor Pro", page_icon="🕵️", layout="wide")

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
def get_best_model():
    """
    Dynamically finds a working model to prevent 404 errors.
    """
    try:
        # Ask Google what models are available for this API Key
        available_models = []
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                available_models.append(m.name)
        
        # Priority list (Newest & Fastest first)
        preferences = [
            'models/gemini-1.5-flash',
            'models/gemini-1.5-flash-latest',
            'models/gemini-1.5-pro',
            'models/gemini-pro',
            'models/gemini-1.0-pro'
        ]
        
        # Pick the first preferred model that actually exists
        for pref in preferences:
            if pref in available_models:
                return pref
        
        # Fallback: Just take the first available model if none match
        return available_models[0] if available_models else 'models/gemini-1.5-flash'
        
    except Exception as e:
        # If listing fails, fallback to standard
        return 'models/gemini-1.5-flash'

def analyze_with_gemini(text_content):
    if "gemini_api_key" not in st.secrets:
        return {"error": "Missing 'gemini_api_key' in Streamlit Secrets!"}
    
    api_key = st.secrets["gemini_api_key"]
    genai.configure(api_key=api_key)
    
    # SMART MODEL SELECTION
    active_model = get_best_model()
    # st.toast(f"Using Model: {active_model}") # Optional: Debugging
    
    prompt = f"""
    You are an expert financial auditor. Extract data from this text into a JSON object.
    
    1. **Dealer & Contact Info:**
       - "dealer_name": (Name of showroom/agency)
       - "dealer_address": (Full address)
       - "dealer_phone": (Phone/Mobile)
       - "dealer_email": (Email)
    
    2. **Bank Details (For Fraud Check):**
       - "bank_name", "account_number", "ifsc_code"
       - "beneficiary_name" (Name on the bank account - Vital for fraud check)
    
    3. **Invoice Details:**
       - "invoice_number", "invoice_date", "customer_name"
       - "terms_summary" (Refund/Cancellation policy)

    4. **Financials (Car Quotation):**
       - "document_type": "CAR_QUOTATION"
       - "ex_showroom", "tcs", "life_tax", "insurance", "extended_warranty"
       - "accessories", "fastag", "vas", "temp_reg", "other_charges", "on_road_price"
       - "car_model", "customer_state"
    
    5. **Financials (GST Invoice):**
       - "document_type": "GST_INVOICE"
       - "gstin", "total_amount"
    
    Rules:
    - Return ONLY valid JSON.
    - If value missing, use 0.0 or null.
    - Convert "1,20,000.00" to 120000.00.
    
    Document Text:
    {text_content}
    """
    
    try:
        model = genai.GenerativeModel(active_model)
        response = model.generate_content(prompt)
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return {"error": f"Model ({active_model}) failed. Error: {str(e)}"}

# --- 4. AUDITOR LOGIC ---
def audit_quotation(data):
    """Checks for overpricing and fraud indicators."""
    warnings = []
    trust_score = 100
    
    # Helper to safely get float values
    def get_val(key):
        val = data.get(key)
        try:
            return float(str(val).replace(",", "")) if val else 0.0
        except:
            return 0.0

    other = get_val('other_charges')
    ex_price = get_val('ex_showroom')
    ins = get_val('insurance')
    tcs = get_val('tcs')
    
    # 1. Handling Charges Check
    if other > 1500:
        warnings.append(f"🚩 **High Handling Charges:** ₹{other}. Courts often rule these illegal.")
        trust_score -= 20

    # 2. Insurance Markup Check
    if ex_price > 0:
        ratio = (ins / ex_price) * 100
        if ratio > 5.0:
            warnings.append(f"🚩 **Expensive Insurance:** {ratio:.1f}% of car value (Standard is 3-4%).")
            trust_score -= 15

    # 3. TCS Rule Check
    if ex_price < 990000 and tcs > 0:
        warnings.append(f"🚩 **TCS Error:** Tax charged on car < ₹10 Lakhs.")
        trust_score -= 10
        
    # 4. Beneficiary Check (Fraud)
    dealer = str(data.get('dealer_name', '')).lower()
    beneficiary = str(data.get('beneficiary_name', '')).lower()
    if len(dealer) > 3 and len(beneficiary) > 3:
        if dealer[:4] not in beneficiary and beneficiary[:4] not in dealer:
            warnings.append(f"🚨 **Name Mismatch:** Dealer is '{data.get('dealer_name')}' but Bank Account is '{data.get('beneficiary_name')}'.")
            trust_score -= 30

    return warnings, max(0, trust_score)

# --- 5. UI LAYOUT ---
st.title("🕵️ Auto-Auditor: Fraud & Price Check")
st.markdown("Upload a document to verify the **Dealer** (Fraud Check) and the **Price** (Auditor Check).")

with st.sidebar:
    if "gemini_api_key" in st.secrets:
        st.success(f"✅ Gemini Key Loaded")
    else:
        st.error("⚠️ Gemini Key MISSING")
    
    st.divider()
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Secret", type="password")

uploaded_file = st.file_uploader("Upload Quotation / Invoice", type=["pdf", "jpg", "png"])

if uploaded_file:
    # --- ONE BUTTON FOR EVERYTHING ---
    if st.button("🚀 Run Fraud & Price Check", type="primary"):
        
        with st.spinner("👀 Reading Document & Finding Best AI Model..."):
            # 1. OCR
            raw_text = extract_text_from_file(uploaded_file)
            # 2. AI Analysis
            data = analyze_with_gemini(raw_text)
        
        if "error" in data:
            st.error("Analysis Failed")
            st.code(data['error'])
        else:
            # --- RESULTS DASHBOARD ---
            st.divider()
            
            # Prepare Data
            flags, score = audit_quotation(data)
            dealer_name = data.get('dealer_name', 'Unknown')
            city = data.get('customer_state', '')
            
            # Smart Search Link
            if dealer_name and dealer_name.lower() != "unknown":
                query = f"{dealer_name} {city} reviews complaints"
                search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                link_markdown = f"👉 **[Click to Verify Dealer Reputation on Google]({search_url})**"
