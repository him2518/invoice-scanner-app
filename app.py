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

# --- 4. PARSING LOGIC (ROW-AWARE) ---
def smart_parse_car_quotation(text):
    data = {}
    
    # 1. Split text into individual lines (Crucial for tables)
    lines = text.split('\n')
    
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

    def extract_val_row_by_row(key):
        keywords = context_map.get(key, [])
        
        # Scan every line in the document
        for i, line in enumerate(lines):
            # If the line contains one of our keywords (e.g., "Road Tax")
            if any(k.lower() in line.lower() for k in keywords):
                
                # Strategy A: Look for price on the SAME line
                # Regex looks for numbers like 1,20,000.00
                matches = re.findall(r"[\d,]+\.\d{2}", line)
                if matches:
                    # Return the LAST number found (Prices are usually in the rightmost column)
                    return float(matches[-1].replace(",", ""))
                
                # Strategy B: If no price on same line, check the NEXT line (Text wrapping)
                if i + 1 < len(lines):
                    next_line = lines[i+1]
                    matches_next = re.findall(r"[\d,]+\.\d{2}", next_line)
                    if matches_next:
                        # Return the first number on the next line
                        return float(matches_next[0].replace(",", ""))
        return 0.0

    for key in context_map:
        data[key] = extract_val_row_by_row(key)

    return data

def parse_gst_invoice(text):
    data = {"type": "GST_INVOICE"}
    gst_match = re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}", text)
    data['gstin'] = gst_match.group(0) if gst_match else None
    
    acc_match = re.search(r"(?:Account|Acc|A/c)[^0-9]*(\d{9,18})", text, re.IGNORECASE)
    data['account'] = acc_match.group(1) if acc_match else None
    
    ifsc_match = re.search(r"[A-Z]{4}0[A-Z0-9]{6}", text)
    data['ifsc'] = ifsc_match.group(0) if ifsc_match else None

    def find_amount(label):
        match = re.search(rf"{label}[^\d]*([\d,]+\.\d{{2}})", text, re.IGNORECASE)
        if match: return float(match.group(1).replace(",", ""))
        return 0.0

    data['cgst'] = find_amount("CGST")
    data['sgst'] = find_amount("SGST")
    data['igst'] = find_amount("IGST")
    return data

# --- 5. UI ---
st.title("🚗 Super Invoice Scanner Pro")
st.write("Upload a **Car Quotation** OR a **GST Invoice**.")

with st.sidebar:
    st.header("🔐 Verification Keys")
    razor_key = st.text_input("Razorpay Key ID", type="password")
    razor_secret = st.text_input("Razorpay Key Secret", type="password")

uploaded_file = st.file_uploader("Upload File", type=["jpg", "png", "pdf"])

if uploaded_file:
    if uploaded_file.type == "application/pdf":
        st.info(f"📄 PDF Loaded: {uploaded_file.name}")
    else:
        st.image(uploaded_file, caption="Preview", width=350)
    
    if st.button("🚀 Analyze Now"):
        with st.spinner("🤖 AI is reading & thinking..."):
            text = get_text_from_file(uploaded_file)
            
            # Smart Detection
            car_keywords = ["Ex-Showroom", "On Road", "Hypothecation", "RTO", "Variant", "Model", "Toyota"]
            is_car = any(k.lower() in text.lower() for k in car_keywords)

            if is_car:
                st.success("✅ Detected: New Car Quotation")
                data = smart_parse_car_quotation(text)
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Ex-Showroom", f"₹{data['ex_showroom']:,.2f}")
                c2.metric("Road Tax (RTO)", f"₹{data['life_tax']:,.2f}")
                c3.metric("On-Road Price", f"₹{data['on_road']:,.2f}", delta="Final")
                
                st.subheader("📋 Smart Cost Breakdown")
                tab1, tab2 = st.tabs(["Essential Costs", "Extras & Accessories"])
                
                with tab1:
                    col1, col2 = st.columns(2)
                    col1.text_input("Insurance", value=f"₹{data['insurance']:,.2f}")
                    col1.text_input("Extended Warranty", value=f"₹{data['extended_warranty']:,.2f}")
                    col2.text_input("TCS", value=f"₹{data['tcs']:,.2f}")
                    col2.text_input("Fastag", value=f"₹{data['fastag']:,.2f}")

                with tab2:
                    col1, col2 = st.columns(2)
                    col1.text_input("Accessories", value=f"₹{data['accessories']:,.2f}")
                    col1.text_input("VAS / Coating", value=f"₹{data['vas']:,.2f}")
                    col2.text_input("Handling", value=f"₹{data['others']:,.2f}")
                    col2.text_input("Temp Registration", value=f"₹{data['temp_reg']:,.2f}")

            else:
                st.success("✅ Detected: GST Invoice")
                data = parse_gst_invoice(text)
                
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("GSTIN", data['gstin'] or "Missing")
                c2.metric("Account No", data['account'] or "Missing")
                c3.metric("IFSC", data['ifsc'] or "Missing")
                c4.metric("Tax Type", "IGST" if data['igst'] > 0 else "Intra-State")
                
                st.write(f"**Tax Breakdown:** CGST: {data['cgst']} | SGST: {data['sgst']} | IGST: {data['igst']}")
