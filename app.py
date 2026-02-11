import streamlit as st
import os
import json
import base64
import time
import urllib.parse
import google.generativeai as genai
import fitz  # PyMuPDF
from PIL import Image
import io

# --- PAGE CONFIG ---
st.set_page_config(page_title="Auto-Auditor Pro", page_icon="🕵️", layout="wide")

# --- 1. SETUP CREDENTIALS ---
# We ONLY need the Gemini Key now. No more Google Cloud Service Account!
if "gemini_api_key" not in st.secrets:
    st.error("⚠️ Critical: 'gemini_api_key' is missing in Streamlit Secrets.")
    st.stop()

api_key = st.secrets["gemini_api_key"]
genai.configure(api_key=api_key)

# --- 2. INPUT PROCESSOR (HANDLES IMAGES & PDFS) ---
def process_uploaded_file(uploaded_file):
    """
    Converts uploads into a format Gemini can understand (Image Bytes).
    """
    try:
        # CASE A: It's already an image
        if uploaded_file.type in ["image/jpeg", "image/png", "image/jpg"]:
            return {
                "mime_type": uploaded_file.type,
                "data": uploaded_file.getvalue()
            }
        
        # CASE B: It's a PDF -> Convert 1st Page to Image
        elif uploaded_file.type == "application/pdf":
            doc = fitz.open(stream=uploaded_file.getvalue(), filetype="pdf")
            page = doc.load_page(0)  # Read first page
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            return {
                "mime_type": "image/png",
                "data": img_bytes
            }
        
    except Exception as e:
        return f"Error processing file: {e}"

# --- 3. THE BRAIN (GEMINI VISION) ---
def analyze_with_gemini(file_data):
    # Model: Gemini 1.5 Flash is excellent at reading documents
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    prompt = """
    You are an expert financial auditor. Look at this document image and extract details into a JSON object.
    
    1. **Dealer Identity (Look at Logos/Headers):**
       - "dealer_name": (Name of showroom/agency. If not clear, look for the biggest logo or bold text at top)
       - "dealer_address": (Full address)
       - "dealer_phone": (Phone/Mobile)
       - "dealer_email": (Email)
    
    2. **Invoice Info:**
       - "invoice_number", "invoice_date", "customer_name"
    
    3. **Bank Details (Vital for Fraud Check):**
       - "bank_name", "account_number", "ifsc_code"
       - "beneficiary_name" (Name on the bank account)
    
    4. **Car Quotation Financials:**
       - "document_type": "CAR_QUOTATION"
       - "ex_showroom", "tcs", "life_tax", "insurance", "extended_warranty"
       - "accessories", "fastag", "vas", "temp_reg", "other_charges", "on_road_price"
       - "car_model", "customer_state"
    
    5. **GST Invoice Financials (If applicable):**
       - "document_type": "GST_INVOICE"
       - "gstin", "total_amount"

    Rules:
    - Return ONLY valid JSON.
    - If a value is missing or unreadable, return null.
    - Standardize money to numbers (e.g., 150000.00).
    """
    
    try:
        # Send Image + Prompt directly to Gemini
        response = model.generate_content([prompt, file_data])
        text = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(text)
    except Exception as e:
        return {"error": str(e)}

# --- 4. AUDITOR LOGIC ---
def audit_quotation(data):
    warnings = []
    trust_score = 100
    
    # Clean up values (Handle None/Null)
    def get_val(key): 
        val = data.get(key)
        return float(val) if val else 0.0

    other = get_val('other_charges')
    ex_price = get_val('ex_showroom')
    ins = get_val('insurance')
    tcs = get_val('tcs')
    
    # 1. Handling Charges
    if other > 1500:
        warnings.append(f"🚩 **High Handling Charges:** ₹{other:,.0f}. Ask for waiver.")
        trust_score -= 20

    # 2. Insurance Markup
    if ex_price > 0:
        ratio = (ins / ex_price) * 100
        if ratio > 5.0:
            warnings.append(f"🚩 **Expensive Insurance:** {ratio:.1f}% of car value (Standard is 3-4%).")
            trust_score -= 15

    # 3. TCS Rule
    if ex_price < 990000 and tcs > 0:
        warnings.append(f"🚩 **TCS Error:** Tax charged on car < ₹10 Lakhs.")
        trust_score -= 10
        
    # 4. Beneficiary Check
    dealer = str(data.get('dealer_name', '')).lower()
    beneficiary = str(data.get('beneficiary_name', '')).lower()
    
    if len(dealer) > 3 and len(beneficiary) > 3:
        # Simple fuzzy match check
        if dealer[:4] not in beneficiary and beneficiary[:4] not in dealer:
            warnings.append(f"🚨 **Name Mismatch:** Dealer is '{data['dealer_name']}' but Bank Account is '{data['beneficiary_name']}'. Verify!")
            trust_score -= 30

    return warnings, max(0, trust_score)

# --- 5. UI LAYOUT ---
st.title("🕵️ Auto-Auditor Pro (Gemini Vision)")
st.markdown("Upload a quotation. We use **AI Vision** to read it directly.")

with st.sidebar:
    if "gemini_api_key" in st.secrets:
        st.success("✅ Gemini Key Active")
    else:
        st.error("⚠️ Gemini Key Missing")
    
    st.divider()
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Secret", type="password")

uploaded_file = st.file_uploader("Upload Quotation (Image/PDF)", type=["pdf", "jpg", "png", "jpeg"])

if uploaded_file:
    if st.button("🚀 Run Fraud & Price Check", type="primary"):
        
        with st.spinner("👀 AI is looking at your document..."):
            # 1. Process File (Convert to Image Bytes)
            file_data = process_uploaded_file(uploaded_file)
            
            if isinstance(file_data, str): # Error caught
                st.error(file_data)
                st.stop()
                
            # 2. AI Analysis
            data = analyze_with_gemini(file_data)
        
        if "error" in data:
            st.error("Analysis Failed")
            st.code(data['error'])
        else:
            # --- RESULTS DASHBOARD ---
            st.divider()
            
            # Prepare Data
            flags, score = audit_quotation(data)
            dealer_name = data.get('dealer_name')
            city = data.get('customer_state', '')

            # --- SMART SEARCH LINK LOGIC ---
            if dealer_name and dealer_name.lower() != "unknown":
                query = f"{dealer_name} {city} reviews complaints"
                search_url = f"https://www.google.com/search?q={urllib.parse.quote(query)}"
                link_markdown = f"👉 **[Click to Verify '{dealer_name}' on Google]({search_url})**"
            else:
                search_url = "#"
                link_markdown = "⚠️ *Could not identify Dealer Name for verification.*"

            # 1. TOP LEVEL SCORE
            c1, c2, c3 = st.columns(3)
            
            # Color coding for score
            score_delta = "Clean" if score == 100 else "Risk"
            score_color = "normal" if score > 80 else "inverse"
            
            c1.metric("🛡️ Trust Score", f"{score}/100", score_delta, delta_color=score_color)
            c2.metric("Final Price", f"₹{data.get('on_road_price', 0):,}")
            c3.metric("Dealer", dealer_name or "Unknown")

            # 2. SPLIT VIEW: FRAUD vs AUDITOR
            col_fraud, col_audit = st.columns(2)

            with col_fraud:
                st.subheader("🏢 Fraud Check (Identity)")
                st.info(f"**Dealer:** {dealer_name}\n\n**Address:** {data.get('dealer_address', 'N/A')}")
                st.write(f"**Bank Beneficiary:** {data.get('beneficiary_name', 'Not Found')}")
                st.write(f"**Account No:** {data.get('account_number', 'N/A')}")
                
                # Check for mismatch logic output
                mismatch = any("Mismatch" in f for f in flags)
                if mismatch:
                    st.error("🚨 BENEFICIARY MISMATCH DETECTED")
                else:
                    st.success("✅ Identity looks consistent")
                
                st.markdown(link_markdown)

            with col_audit:
                st.subheader("💰 Auditor Check (Pricing)")
                st.write(f"**Ex-Showroom:** ₹{data.get('ex_showroom', 0):,}")
                st.write(f"**Insurance:** ₹{data.get('insurance', 0):,}")
                st.write(f"**Handling Charges:** ₹{data.get('other_charges', 0):,}")
                
                if flags:
                    st.warning("⚠️ Audit Findings:")
                    for f in flags:
                        st.write(f)
                else:
                    st.success("✅ Pricing looks fair and clean.")

            # 3. DETAILS EXPANDER
            with st.expander("📄 View Full Extracted Details"):
                st.json(data)
