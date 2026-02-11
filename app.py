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
st.set_page_config(page_title="Auto-Auditor AI", page_icon="🕵️", layout="wide")

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
    api_key = st.secrets.get("gemini_api_key")
    if not api_key and "google_credentials" in st.secrets:
        api_key = st.secrets["google_credentials"].get("gemini_api_key")
    
    if not api_key:
        return {"error": "CRITICAL: 'gemini_api_key' not found in Secrets."}
    
    genai.configure(api_key=api_key)
    
    # Models to try (Self-Healing Logic)
    model_candidates = [
        'models/gemini-2.0-flash',
        'models/gemini-1.5-flash',
        'models/gemini-pro'
    ]
    
    # --- UPDATED PROMPT WITH AUDIT FIELDS ---
    prompt = f"""
    You are an expert financial auditor. Extract specific details from this car quotation/invoice into a JSON object.
    
    1. **Dealer Identity:**
       - "dealer_name": (Name of the showroom/agency)
       - "dealer_address": (Full address printed on document)
       - "dealer_phone": (Phone/Mobile numbers)
       - "dealer_email": (Email address)
    
    2. **Invoice/Quote Details:**
       - "invoice_number": (Invoice or Quotation No)
       - "invoice_date": (Date of issue)
       - "customer_name": (Buyer's name)
    
    3. **Bank Details (For Fraud Check):**
       - "bank_name": (Bank name listed for payment)
       - "account_number": (Account No)
       - "ifsc_code": (IFSC Code)
       - "beneficiary_name": (Name on the bank account - vital for fraud check)
    
    4. **Financials (Car Quotation):**
       - "document_type": "CAR_QUOTATION"
       - "car_model", "ex_showroom", "tcs", "life_tax", "insurance", "insurance_type"
       - "extended_warranty", "accessories", "fastag", "vas", "hypothecation_charges"
       - "temp_reg", "other_charges", "discount_amount", "on_road_price"
       - "customer_state"
    
    5. **Terms & Conditions:**
       - "terms_summary": (Summarize cancellation/booking refund policy in 1 sentence)
    
    Rules:
    - Return ONLY valid JSON.
    - If value missing, use 0.0 or null.
    - Standardize currency to float (e.g. 120000.00).
    
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

# --- 4. THE AUDITOR LAYER (LOGIC & MATH) ---
def audit_quotation(data):
    """
    Analyzes the extracted JSON for fraud, overpricing, and errors.
    """
    warnings = []
    trust_score = 100
    
    # 1. Handling/Logistics Charges (Often Illegal)
    other = data.get('other_charges', 0)
    if other > 1500:
        warnings.append(f"🚩 **High Handling Charges:** ₹{other}. Many courts have ruled these illegal. Ask for a waiver.")
        trust_score -= 20

    # 2. Insurance Overpricing Check
    ex_price = data.get('ex_showroom', 0)
    ins = data.get('insurance', 0)
    
    if ex_price > 0:
        ratio = (ins / ex_price) * 100
        if ratio > 5.0:
            warnings.append(f"🚩 **Expensive Insurance:** Premium is {ratio:.1f}% of car value. Standard market rate is 3-4%. Check for hidden add-ons.")
            trust_score -= 15

    # 3. TCS Rule Check (Only applicable > 10 Lakhs)
    tcs = data.get('tcs', 0)
    if ex_price < 990000 and tcs > 0:
        warnings.append(f"🚩 **TCS Error:** ₹{tcs} charged, but car price is under ₹10 Lakhs. This tax usually doesn't apply.")
        trust_score -= 10
        
    # 4. Beneficiary Name Mismatch (Fraud Check)
    dealer_name = str(data.get('dealer_name', '')).lower()
    beneficiary = str(data.get('beneficiary_name', '')).lower()
    
    # Simple check: if we have both names, and they look totally different
    if dealer_name and beneficiary and len(dealer_name) > 3:
        if dealer_name[:4] not in beneficiary and beneficiary[:4] not in dealer_name:
            warnings.append(f"🚨 **Potential Fraud:** Dealer name is '{data['dealer_name']}' but Bank Account Name is '{data['beneficiary_name']}'. Verify before transferring money.")
            trust_score -= 30

    # 5. Math Integrity Check
    calculated_total = (
        ex_price + 
        data.get('life_tax', 0) + 
        ins + 
        data.get('extended_warranty', 0) + 
        data.get('accessories', 0) + 
        data.get('fastag', 0) + 
        data.get('vas', 0) + 
        other + 
        data.get('temp_reg', 0) + 
        tcs +
        data.get('hypothecation_charges', 0)
    ) - data.get('discount_amount', 0)
    
    on_road = data.get('on_road_price', 0)
    diff = abs(on_road - calculated_total)
    
    if diff > 1000:
         warnings.append(f"⚠️ **Math Mismatch:** Items sum to ₹{calculated_total:,.0f}, but Total says ₹{on_road:,.0f}. Difference: ₹{diff:,.0f}")
         trust_score -= 10

    return warnings, max(0, trust_score)

# --- 5. UI LAYOUT ---
st.title("🕵️ Auto-Auditor: Fraud & Price Check")
st.markdown("Upload a Quotation. We extract details, **check for fraud**, and **audit the price**.")

# Sidebar
with st.sidebar:
    if "gemini_api_key" in st.secrets or ("google_credentials" in st.secrets and "gemini_api_key" in st.secrets["google_credentials"]):
        st.success("✅ AI Key Loaded")
    else:
        st.error("⚠️ AI Key Missing")
    st.divider()
    st.header("🔐 Other Keys")
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Secret", type="password")

uploaded_file = st.file_uploader("Upload Document", type=["pdf", "jpg", "png"])

if uploaded_file:
    if st.button("🚀 Analyze & Audit"):
        with st.spinner("👀 Extracting Data..."):
            raw_text = extract_text_from_file(uploaded_file)
        
        with st.spinner("🧠 AI is auditing..."):
            data = analyze_with_gemini(raw_text)
        
        if "error" in data:
            st.error("Analysis Failed")
            st.code(data['error'])
        else:
            # --- 1. FRAUD CHECK SECTION ---
            st.header("🛡️ Fraud & Identity Check")
            
            col1, col2 = st.columns(2)
            dealer_name = data.get('dealer_name', 'Unknown Dealer')
            city = data.get('customer_state', '')
            
            # Generate Google Search Link for Validation
            query = f"{dealer_name} {city} reviews complaints"
            search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
            
            with col1:
                st.subheader("🏢 Dealer Identity")
                st.write(f"**Name:** {dealer_name}")
                st.write(f"**Address:** {data.get('dealer_address', 'N/A')}")
                st.write(f"**Contact:** {data.get('dealer_phone', 'N/A')} | {data.get('dealer_email', 'N/A')}")
                st.markdown(f"👉 **[Click to Verify Rating & Reviews on Google]({search_url})**")
                
            with col2:
                st.subheader("🏦 Bank Validation")
                st.write(f"**Bank:** {data.get('bank_name', 'N/A')}")
                st.write(f"**Account:** {data.get('account_number', 'N/A')}")
                st.write(f"**IFSC:** {data.get('ifsc_code', 'N/A')}")
                st.write(f"**Beneficiary:** {data.get('beneficiary_name', 'N/A')}")
                st.caption("⚠️ Ensure payment is made ONLY to the official dealership account.")

            st.divider()

            # --- 2. AUDIT & PRICE SECTION ---
            st.header("💰 Price & Audit Report")
            
            # Run Audit
            flags, score = audit_quotation(data)
            
            # Score Card
            c1, c2, c3 = st.columns(3)
            if score == 100:
                c1.metric("Trust Score", f"{score}/100", delta="Clean")
            elif score > 70:
                c1.metric("Trust Score", f"{score}/100", delta="Warning", delta_color="off")
            else:
                c1.metric("Trust Score", f"{score}/100", delta="High Risk", delta_color="inverse")
                
            c2.metric("Final Price", f"₹{data.get('on_road_price', 0):,}")
            c3.metric("Ex-Showroom", f"₹{data.get('ex_showroom', 0):,}")

            # Warning Display
            if flags:
                st.error("🚨 **Audit Findings (Red Flags):**")
                for f in flags:
                    st.write(f)
            else:
                st.success("✅ **Clean Audit:** No overpricing or fraud signals detected.")

            # Detailed Tabs
            tab1, tab2, tab3 = st.tabs(["Cost Breakdown", "Document Info", "Terms & Conditions"])
            
            with tab1:
                col1, col2 = st.columns(2)
                col1.text_input("Insurance Premium", value=f"₹{data.get('insurance', 0)}")
                col1.text_input("Extended Warranty", value=f"₹{data.get('extended_warranty', 0)}")
                col1.text_input("Hypothecation (Loan) Charges", value=f"₹{data.get('hypothecation_charges', 0)}")
                
                col2.text_input("Handling/Logistics", value=f"₹{data.get('other_charges', 0)}")
                col2.text_input("Accessories", value=f"₹{data.get('accessories', 0)}")
                col2.text_input("Discounts", value=f"₹{data.get('discount_amount', 0)}")
                st.info(f"Insurance Type: {data.get('insurance_type', 'Standard')}")

            with tab2:
                st.write(f"**Invoice No:** {data.get('invoice_number', 'N/A')}")
                st.write(f"**Date:** {data.get('invoice_date', 'N/A')}")
                st.write(f"**Customer:** {data.get('customer_name', 'N/A')}")
                st.write(f"**Model:** {data.get('car_model', 'N/A')}")
            
            with tab3:
                st.write(f"**Policy Summary:** {data.get('terms_summary', 'No specific terms extracted.')}")
