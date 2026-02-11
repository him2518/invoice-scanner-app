import streamlit as st
import os
import json
import base64
import requests
import google.generativeai as genai
from google.cloud import vision
import fitz  # PyMuPDF

# --- PAGE CONFIG ---
st.set_page_config(page_title="Smart Doc Analyzer (Gemini AI)", page_icon="🧠", layout="wide")

# --- 1. SETUP CREDENTIALS ---

# A. Google Cloud Vision (OCR) Setup
# We check if the key is in Streamlit Secrets (Cloud) or a local file
if "google_credentials" in st.secrets:
    try:
        # Decode the base64 key from Secrets
        encoded_key = st.secrets["google_credentials"]["encoded_key"]
        decoded_key = base64.b64decode(encoded_key).decode("utf-8")
        
        # Write to a temporary file for the library to use
        with open("service_account.json", "w") as f:
            f.write(decoded_key)
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
    except Exception as e:
        st.error(f"❌ Error setting up OCR Credentials: {e}")
        st.stop()
elif os.path.exists("service_account.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
else:
    st.warning("⚠️ OCR Keys missing. Please add 'service_account.json' or set Secrets.")

# --- 2. THE EYES (OCR ENGINE) ---
def extract_text_from_file(uploaded_file):
    """
    Uses Google Cloud Vision to read text from PDF or Images.
    """
    try:
        client = vision.ImageAnnotatorClient()
        content = uploaded_file.getvalue()
        image = None

        # Handle PDF vs Image
        if uploaded_file.type == "application/pdf":
            doc = fitz.open(stream=content, filetype="pdf")
            page = doc.load_page(0)  # Read first page
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            image = vision.Image(content=img_bytes)
        else:
            image = vision.Image(content=content)
        
        # Perform OCR
        response = client.document_text_detection(image=image)
        return response.full_text_annotation.text
    except Exception as e:
        return f"Error: {e}"

# --- 3. THE BRAIN (GEMINI AI) ---
def analyze_with_gemini(text_content, api_key):
    """
    Sends the raw text to Gemini and asks for a structured JSON response.
    """
    # Configure Gemini
    genai.configure(api_key=api_key)
    
    # Use the fast and smart 'flash' model
    model = genai.GenerativeModel('gemini-1.5-flash')
    
    # The "Prompt" - This instructions the AI on what to find
    prompt = f"""
    You are an expert financial document analyzer. I will provide you with text extracted from a document.
    
    Your task is to:
    1. Identify if the document is a "CAR_QUOTATION" or a "GST_INVOICE".
    2. Extract specific fields based on the type.
    3. Return the result ONLY as a pure JSON object. No markdown, no comments.
    
    --- 
    If it is a **CAR_QUOTATION**, extract these fields:
    - "document_type": "CAR_QUOTATION"
    - "ex_showroom": (The basic vehicle price)
    - "tcs": (Tax Collected at Source / 1% Tax)
    - "life_tax": (Road Tax / RTO / Registration Charges / Permanent Reg)
    - "insurance": (Total Insurance Premium / Zero Dep / Bumper to Bumper)
    - "extended_warranty": (Any warranty / Shield / T-Secure / Protection Plan)
    - "accessories": (Kit / Mud Flaps / Mats / Fitting Charges)
    - "fastag": (Fastag / RFID Tag)
    - "vas": (Value Added Services / Teflon / Coating / Anti-Rust)
    - "temp_reg": (Temporary Registration / TR Charges)
    - "other_charges": (Handling / Logistics / Depot / Misc)
    - "on_road_price": (The Final Grand Total Amount)
    - "customer_name": (Name of the buyer if found)
    - "car_model": (Model name if found, e.g., Toyota Rumion)
    
    If it is a **GST_INVOICE**, extract these fields:
    - "document_type": "GST_INVOICE"
    - "gstin": (The 15-digit GST Number)
    - "account_number": (Bank Account Number)
    - "ifsc_code": (Bank IFSC Code)
    - "invoice_date": (Date of invoice)
    - "total_amount": (Final Invoice Value)
    - "cgst_amount": (Total CGST)
    - "sgst_amount": (Total SGST)
    - "igst_amount": (Total IGST)
    
    ---
    **Rules:**
    - If a value is not found, set it to 0.0 or null (do not make it up).
    - Convert all currency strings (e.g., "1,20,000.00") to pure numbers (float).
    
    **Document Text:**
    {text_content}
    """
    
    try:
        response = model.generate_content(prompt)
        # Clean up code blocks if Gemini adds them
        clean_json = response.text.replace("```json", "").replace("```", "").strip()
        return json.loads(clean_json)
    except Exception as e:
        return {"error": str(e)}

# --- 4. VERIFICATION (Optional) ---
def verify_gst_gov(gstin, r_key, r_secret):
    if not r_key or not r_secret: return None
    url = f"https://api.razorpay.com/v1/gst/gstin/{gstin}"
    try:
        return requests.get(url, auth=(r_key, r_secret)).json()
    except: return None

# --- 5. UI LAYOUT ---
st.title("🧠 Smart Document Analyzer")
st.markdown("Upload any **Car Quotation** or **Invoice**. Gemini AI will extract every detail.")

# Sidebar
with st.sidebar:
    st.header("🔑 API Keys")
    
    # Allow user to input Gemini Key if not in secrets
    if "gemini_api_key" in st.secrets:
        gemini_key = st.secrets["gemini_api_key"]
        st.success("✅ Gemini Key Loaded")
    else:
        gemini_key = st.text_input("Gemini API Key", type="password")
        st.caption("Get key from [Google AI Studio](https://aistudio.google.com/)")

    st.divider()
    st.subheader("Government Verification")
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Secret", type="password")

# File Uploader
uploaded_file = st.file_uploader("Upload Document (PDF/Image)", type=["pdf", "jpg", "png", "jpeg"])

if uploaded_file and gemini_key:
    # 1. Preview
    if uploaded_file.type == "application/pdf":
        st.info(f"📄 PDF Uploaded: {uploaded_file.name}")
    else:
        st.image(uploaded_file, caption="Document Preview", width=400)
    
    # 2. Analyze Button
    if st.button("🚀 Analyze Document"):
        
        # Step A: OCR
        with st.spinner("👀 Reading text..."):
            raw_text = extract_text_from_file(uploaded_file)
        
        # Step B: Gemini Analysis
        with st.spinner("🧠 Gemini is analyzing..."):
            data = analyze_with_gemini(raw_text, gemini_key)
        
        # Step C: Display Results
        if "error" in data:
            st.error(f"Analysis Failed: {data['error']}")
        else:
            doc_type = data.get("document_type", "UNKNOWN")
            
            # === LAYOUT FOR CAR QUOTATION ===
            if doc_type == "CAR_QUOTATION":
                st.success(f"✅ Detected: Car Quotation ({data.get('car_model', 'Unknown Model')})")
                
                # Big Metrics
                col1, col2, col3 = st.columns(3)
                col1.metric("Ex-Showroom Price", f"₹{data.get('ex_showroom', 0):,}")
                col2.metric("Road Tax (RTO)", f"₹{data.get('life_tax', 0):,}")
                col3.metric("On-Road Price", f"₹{data.get('on_road_price', 0):,}", delta="Final")
                
                st.divider()
                st.subheader("📋 Detailed Breakdown")
                
                # Tabbed View for cleaner details
                tab_main, tab_extras = st.tabs(["Essential Costs", "Extras & Accessories"])
                
                with tab_main:
                    c1, c2 = st.columns(2)
                    c1.text_input("Insurance Premium", value=f"₹{data.get('insurance', 0)}")
                    c1.text_input("Extended Warranty", value=f"₹{data.get('extended_warranty', 0)}")
                    c2.text_input("TCS (1% Tax)", value=f"₹{data.get('tcs', 0)}")
                    c2.text_input("Fastag / RFID", value=f"₹{data.get('fastag', 0)}")
                
                with tab_extras:
                    c1, c2 = st.columns(2)
                    c1.text_input("Accessories Kit", value=f"₹{data.get('accessories', 0)}")
                    c1.text_input("VAS (Teflon/Coating)", value=f"₹{data.get('vas', 0)}")
                    c2.text_input("Temp Registration", value=f"₹{data.get('temp_reg', 0)}")
                    c2.text_input("Other / Logistics", value=f"₹{data.get('other_charges', 0)}")

            # === LAYOUT FOR GST INVOICE ===
            elif doc_type == "GST_INVOICE":
                st.success("✅ Detected: GST Invoice")
                
                col1, col2, col3 = st.columns(3)
                col1.metric("GSTIN", data.get("gstin", "N/A"))
                col2.metric("Invoice Date", data.get("invoice_date", "N/A"))
                col3.metric("Total Amount", f"₹{data.get('total_amount', 0):,}")
                
                st.subheader("🏦 Bank Details")
                st.write(f"**Account No:** {data.get('account_number', 'Not Found')}")
                st.write(f"**IFSC Code:** {data.get('ifsc_code', 'Not Found')}")
                
                st.subheader("💰 Tax Split")
                st.write(f"CGST: ₹{data.get('cgst_amount', 0)} | SGST: ₹{data.get('sgst_amount', 0)} | IGST: ₹{data.get('igst_amount', 0)}")
                
                # Verification Button
                if data.get("gstin") and razor_key:
                    if st.button("Verify GSTIN"):
                        with st.spinner("Connecting to Govt Database..."):
                            v_data = verify_gst_gov(data['gstin'], razor_key, razor_secret)
                            st.json(v_data)

            # === FALLBACK / RAW DATA ===
            else:
                st.warning("Could not automatically classify document type.")
                st.write(data)

            # Always show the raw JSON in an expander for debugging
            with st.expander("🔍 View Raw JSON Response"):
                st.json(data)

elif not gemini_key:
    st.info("👈 Please enter your Gemini API Key in the sidebar to start.")
