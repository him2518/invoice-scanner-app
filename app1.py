import streamlit as st
import os
import re
import requests  # New library for API calls

# --- CONFIGURATION ---
st.set_page_config(page_title="Invoice Scanner Pro", page_icon="🧾", layout="wide")

# --- 1. SETUP GOOGLE CREDENTIALS ---
if os.path.exists("service_account.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
else:
    st.error("❌ Critical: 'service_account.json' not found.")
    st.stop()

# --- 2. IMPORT LIBRARIES SAFELY ---
try:
    from google.cloud import vision
    import fitz  # PyMuPDF
except ImportError as e:
    st.error(f"❌ Missing Library: {e}")
    st.stop()

# --- 3. THE "TRUTH" ENGINE (API CALLS) ---
def verify_gst_razorpay(gstin, api_key, api_secret):
    """
    Connects to Razorpay to check if GSTIN is real.
    """
    url = f"https://api.razorpay.com/v1/gst/gstin/{gstin}"
    try:
        response = requests.get(url, auth=(api_key, api_secret))
        return response.json()
    except Exception as e:
        return {"error": str(e)}

def verify_bank_razorpay(account, ifsc, api_key, api_secret):
    """
    Drops ₹1 (Penny Drop) to check if Bank Account exists.
    """
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
        "amount": 100, # 100 paise = ₹1
        "currency": "INR"
    }
    try:
        response = requests.post(url, json=data, auth=(api_key, api_secret))
        return response.json()
    except Exception as e:
        return {"error": str(e)}

# --- 4. THE "EYES" ENGINE (OCR) ---
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

# --- 5. THE "BRAIN" ENGINE (EXTRACTION) ---
def extract_details(text):
    data = {}
    
    # Extract GSTIN
    gst_match = re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}", text)
    data['gstin'] = gst_match.group(0) if gst_match else None

    # Extract Account Number
    acc_match = re.search(r"(?:Account|Acc|A/c)[^0-9]*(\d{9,18})", text, re.IGNORECASE)
    data['account'] = acc_match.group(1) if acc_match else None
    
    # Extract IFSC (New!)
    ifsc_match = re.search(r"[A-Z]{4}0[A-Z0-9]{6}", text)
    data['ifsc'] = ifsc_match.group(0) if ifsc_match else None

    # Extract Amounts
    def find_amount(label):
        match = re.search(rf"{label}[^\d]*([\d,]+\.\d{{2}})", text, re.IGNORECASE)
        if match: return float(match.group(1).replace(",", ""))
        return 0.0

    data['cgst'] = find_amount("CGST")
    data['sgst'] = find_amount("SGST")
    data['igst'] = find_amount("IGST")
    
    return data

# --- 6. APP UI ---
st.title("🧾 Invoice Validator Pro")

# SIDEBAR FOR KEYS
with st.sidebar:
    st.header("🔐 API Keys")
    st.info("Get keys from razorpay.com")
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Key Secret", type="password")
    has_keys = razor_key and razor_secret

uploaded_file = st.file_uploader("Upload Invoice", type=["jpg", "png", "pdf"])

if uploaded_file:
    if uploaded_file.type == "application/pdf":
        st.info(f"📄 PDF Loaded: {uploaded_file.name}")
    else:
        st.image(uploaded_file, caption="Preview", width=300)
    
    if st.button("🚀 Analyze & Verify"):
        with st.spinner("Analyzing..."):
            text = get_text_from_file(uploaded_file)
            data = extract_details(text)
            
            # --- DISPLAY RESULTS ---
            st.divider()
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("GSTIN", data['gstin'] or "Missing")
            col2.metric("Account No", data['account'] or "Missing")
            col3.metric("IFSC Code", data['ifsc'] or "Missing")
            col4.metric("Tax Type", "IGST" if data['igst'] > 0 else "Intra-State")

            # --- VERIFICATION SECTION ---
            st.subheader("🏛️ Government Verification")
            
            if not has_keys:
                st.warning("⚠️ Enter API Keys in the sidebar to verify this data.")
            else:
                # 1. VERIFY GST
                if data['gstin']:
                    st.write(f"Connecting to Government Database for **{data['gstin']}**...")
                    gst_result = verify_gst_razorpay(data['gstin'], razor_key, razor_secret)
                    
                    if "error" in gst_result:
                         st.error(f"API Error: {gst_result['error']}")
                    elif gst_result.get("taxpayer_status") == "Active":
                         st.success(f"✅ GSTIN VALID & ACTIVE")
                         st.json(gst_result) # Show full details
                    else:
                         st.error(f"❌ GSTIN STATUS: {gst_result.get('taxpayer_status', 'Unknown')}")
                
                # 2. VERIFY BANK
                st.divider()
                st.subheader("🏦 Bank Verification")
                if data['account'] and data['ifsc']:
                    st.write(f"Verifying Account **{data['account']}**...")
                    bank_result = verify_bank_razorpay(data['account'], data['ifsc'], razor_key, razor_secret)
                    
                    if "active" in str(bank_result):
                         st.success("✅ BANK ACCOUNT EXISTS")
                         st.write(f"**Registered Name:** {bank_result.get('fund_account', {}).get('bank_account', {}).get('name', 'N/A')}")
                    else:
                         st.error("❌ Bank Verification Failed")
                         st.json(bank_result)
                else:
                    st.info("Need both Account Number and IFSC to verify bank details.")