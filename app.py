import streamlit as st
import os
import json
import base64
import time
import re
import urllib.parse
import google.generativeai as genai
from google.cloud import vision
import fitz  # PyMuPDF

# --- PAGE CONFIG ---
st.set_page_config(page_title="Auto-Auditor (Debug Mode)", page_icon="🛠️", layout="wide")

# --- 1. SETUP CREDENTIALS ---
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

# --- 2. ENHANCED OCR ENGINE ---
def extract_text_from_file(uploaded_file):
    """
    Tries 2 methods to get text:
    1. Direct PDF Text (Fast, Digital PDFs)
    2. Vision OCR (Slow, Scanned PDFs/Images)
    """
    text = ""
    try:
        # Method 1: PyMuPDF (Direct Text)
        if uploaded_file.type == "application/pdf":
            doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
            for page in doc:
                text += page.get_text() + "\n"
        
        # Method 2: Google Vision (Fallback if text is too short)
        if len(text) < 50:
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
            text = response.full_text_annotation.text
            
        return text
    except Exception as e:
        return f"Error reading file: {e}"

# --- 3. THE BRAIN (GEMINI AI) ---
def analyze_with_gemini(text_content):
    # GET KEY
    api_key = st.secrets.get("gemini_api_key")
    if not api_key and "google_credentials" in st.secrets:
        api_key = st.secrets["google_credentials"].get("gemini_api_key")
    
    if not api_key:
        return {"error": "CRITICAL: 'gemini_api_key' not found in Secrets."}
    
    genai.configure(api_key=api_key)
    
    # Switched 1.5-flash to priority #1 (More stable for JSON)
    model_candidates = [
        'models/gemini-1.5-flash',
        'models/gemini-2.0-flash',
        'models/gemini-pro'
    ]
    
    prompt = f"""
    You are an expert financial auditor. Extract details from this text into a JSON object.
    
    IMPORTANT: Extract all currency values as STRINGS first (e.g. "1,50,000.00" or "Rs. 4500"). 
    Do not convert them to numbers yet.
    
    1. **Dealer Info:** "dealer_name", "dealer_address", "dealer_phone", "dealer_email"
    2. **Invoice Info:** "invoice_number", "invoice_date", "customer_name", "customer_state"
    3. **Bank Info:** "bank_name", "account_number", "ifsc_code", "beneficiary_name"
    
    4. **Car Quotation Financials (Keys must be exact):**
       - "document_type": "CAR_QUOTATION"
       - "car_model"
       - "ex_showroom" (Basic cost)
       - "tcs" (Tax Collected Source)
       - "life_tax" (Road Tax/RTO)
       - "insurance" (Premium)
       - "insurance_type" (Zero Dep / Standard)
       - "extended_warranty"
       - "accessories"
       - "hypothecation_charges" (HP/Loan charges)
       - "fastag"
       - "vas" (Value Added Services)
       - "other_charges" (Handling/Logistics/Depot)
       - "discount_amount"
       - "on_road_price" (Grand Total)
       - "terms_summary"
    
    Rules:
    - Return ONLY valid JSON.
    - If a value is missing, return "0" (String).
    
    Document Text:
    {text_content}
    """
    
    last_error = ""
    for model_name in model_candidates:
        try:
            model = genai.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            clean_text = response.text.replace("```json", "").replace("```", "").strip()
            return json.loads(clean_text)
        except Exception as e:
            last_error = str(e)
            if "429" in last_error:
                time.sleep(2)
                continue
                
    return {"error": f"AI Parsing Failed. Last Error: {last_error}"}

# --- 4. CLEANER & AUDITOR ---
def clean_currency(value):
    """Converts string 'Rs. 1,20,000' to float 120000.0"""
    if not value: return 0.0
    if isinstance(value, (int, float)): return float(value)
    
    # Remove non-numeric chars except dot
    clean = re.sub(r'[^\d.]', '', str(value))
    try:
        return float(clean)
    except:
        return 0.0

def audit_quotation(data):
    warnings = []
    trust_score = 100
    
    # Convert all fields to floats for math
    ex_price = clean_currency(data.get('ex_showroom', 0))
    insurance = clean_currency(data.get('insurance', 0))
    other = clean_currency(data.get('other_charges', 0))
    tcs = clean_currency(data.get('tcs', 0))
    on_road = clean_currency(data.get('on_road_price', 0))
    
    # 1. Handling Charges
    if other > 1500:
        warnings.append(f"🚩 **High Handling Charges:** ₹{other:,.0f}. Ask for waiver.")
        trust_score -= 20

    # 2. Insurance Markup
    if ex_price > 0:
        ratio = (insurance / ex_price) * 100
        if ratio > 5.0:
            warnings.append(f"🚩 **Expensive Insurance:** {ratio:.1f}% of car value (Standard is 3-4%).")
            trust_score -= 15

    # 3. TCS Check
    if ex_price < 990000 and tcs > 0:
        warnings.append(f"🚩 **TCS Error:** ₹{tcs:,.0f} charged on car < ₹10 Lakhs.")
        trust_score -= 10
        
    # 4. Beneficiary Check
    dealer = str(data.get('dealer_name', '')).lower()
    beneficiary = str(data.get('beneficiary_name', '')).lower()
    if len(dealer) > 3 and len(beneficiary) > 3:
        if dealer[:4] not in beneficiary and beneficiary[:4] not in dealer:
            warnings.append(f"🚨 **Bank Name Mismatch:** Paying '{beneficiary}' instead of '{dealer}'?")
            trust_score -= 30

    return warnings, max(0, trust_score), {
        "ex_showroom": ex_price, "insurance": insurance, "other": other, "on_road": on_road
    }

# --- 5. UI LAYOUT ---
st.title("🛠️ Auto-Auditor (Diagnostic Mode)")
st.caption("If you see zeros, check the 'Raw Extracted Text' expander below.")

# Sidebar
with st.sidebar:
    if "gemini_api_key" in st.secrets or ("google_credentials" in st.secrets and "gemini_api_key" in st.secrets["google_credentials"]):
        st.success("✅ AI Key Loaded")
    else:
        st.error("⚠️ AI Key Missing")
    st.divider()
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Secret", type="password")

uploaded_file = st.file_uploader("Upload Document", type=["pdf", "jpg", "png"])

if uploaded_file:
    if st.button("🚀 Analyze & Debug"):
        # 1. READ TEXT
        with st.spinner("👀 Extracting Text..."):
            raw_text = extract_text_from_file(uploaded_file)
            
        # DEBUG: Show what we found
        with st.expander("🔍 View Raw Extracted Text (Check this if results are 0)"):
            st.text(raw_text)
            
        if len(raw_text) < 10:
            st.error("⚠️ No text found! The document might be blank or unreadable.")
            st.stop()

        # 2. ASK AI
        with st.spinner("🧠 AI is analyzing..."):
            raw_json = analyze_with_gemini(raw_text)
            
        # DEBUG: Show raw AI response
        with st.expander("🤖 View Raw AI Response"):
            st.json(raw_json)

        if "error" in raw_json:
            st.error("AI Analysis Failed")
            st.code(raw_json['error'])
        else:
            # 3. AUDIT
            flags, score, clean_vals = audit_quotation(raw_json)
            
            # --- RESULTS SECTION ---
            st.header(f"Trust Score: {score}/100")
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Final Price", f"₹{clean_vals['on_road']:,.0f}")
            c2.metric("Ex-Showroom", f"₹{clean_vals['ex_showroom']:,.0f}")
            c3.metric("Dealer", raw_json.get('dealer_name', 'Unknown'))

            if flags:
                st.error("🚨 Red Flags Found:")
                for f in flags: st.write(f)
            else:
                st.success("✅ No major red flags found.")

            # DETAILED BREAKDOWN
            tab1, tab2 = st.tabs(["💰 Financials", "🏢 Identity"])
            
            with tab1:
                col1, col2 = st.columns(2)
                col1.text_input("Insurance", value=raw_json.get('insurance', '0'))
                col1.text_input("Warranty", value=raw_json.get('extended_warranty', '0'))
                col1.text_input("TCS", value=raw_json.get('tcs', '0'))
                
                col2.text_input("Handling Charges", value=raw_json.get('other_charges', '0'))
                col2.text_input("Accessories", value=raw_json.get('accessories', '0'))
                col2.text_input("Hypothecation", value=raw_json.get('hypothecation_charges', '0'))
            
            with tab2:
                st.write(f"**Dealer:** {raw_json.get('dealer_name')}")
                st.write(f"**Address:** {raw_json.get('dealer_address')}")
                st.write(f"**Bank Beneficiary:** {raw_json.get('beneficiary_name')}")
                st.write(f"**Account:** {raw_json.get('account_number')}")
