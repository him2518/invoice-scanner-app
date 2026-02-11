import streamlit as st
import os
import re
import requests
import base64
import json
import difflib # <-- NEW: The "Fuzzy" Logic Library

# --- CONFIGURATION ---
st.set_page_config(page_title="Super Scanner (Invoice + Car)", page_icon="🚗")

# --- 1. SETUP GOOGLE CREDENTIALS (BASE64 METHOD) ---
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
    st.error("❌ Critical: Google Credentials not found.")
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
    
    # DOCUMENT_TEXT_DETECTION is best for handwriting
    response = client.document_text_detection(image=image)
    return response.full_text_annotation.text

# --- 4. SMART EXTRACTION LOGIC ---

def smart_parse_car_quotation(text):
    """
    Extracts car fields using Synonyms & Context Mapping.
    """
    data = {}
    
    # A. The "Dictionary" of Contexts
    # We map Standard Fields to MANY possible variations (Handwritten or Printed)
    context_map = {
        'ex_showroom': ["Ex-Showroom", "Basic Price", "Unit Cost", "Vehicle Cost", "Showroom Price"],
        'tcs': ["TCS", "Tax Collected", "T.C.S", "1% Tax"],
        'life_tax': ["Life Tax", "Road Tax", "RTO", "Registration", "Govt Fee", "Regn Charges"],
        'fastag': ["Fastag", "Fast Tag", "Tag Cost", "RFID"],
        'temp_reg': ["Temp", "Temporary", "TR Charges", "Tmp Reg"],
        
        'insurance': ["Insurance", "Comprehensive", "OD Premium", "Bumper to Bumper", "Zero Dep", "Policy", "Ins Amount"],
        'extended_warranty': ["Extended Warranty", "Ext Warranty", "EW", "Shield", "Protection Plan"],
        'rsa': ["RSA", "Roadside", "Assistance", "Road Side"],
        
        'accessories': ["Accessories", "Kit", "Fitting", "Acc.", "Mud Flap", "Mats", "Basic Kit"],
        'vas': ["VAS", "Value Added", "Coating", "Teflon", "Anti Rust"],
        'others': ["Others", "Misc", "Handling", "Logistics", "Depot Charges", "H.C."],
        
        'on_road': ["On Road", "Total", "Net Amount", "Grand Total", "Final Price", "To Pay"]
    }

    def extract_value_smart(field_key):
        """
        1. Tries exact keywords.
        2. Tries to find handwritten numbers near the keywords.
        """
        keywords = context_map.get(field_key, [])
        
        # Regex Explanation:
        # (?: ... ) -> Match any of the keywords
        # [^\d\n]* -> Allow spaces, colons, or dashes (but not new lines)
        # ([\d,]+\.?\d*) -> Capture the number
        pattern = rf"(?:{'|'.join(keywords)})[^\d\n]*([\d,]+\.?\d*)"
        
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw_val = match.group(1).replace(",", "")
            try:
                return float(raw_val)
            except:
                return 0.0
        return 0.0

    # Run the extractor for all fields
    for key in context_map:
        data[key] = extract_value_smart(key)

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

# --- 5. UI & LOGIC ---
st.title("🚗 Smart Quotation Scanner")
st.write("Upload a **Car Quotation** OR a **GST Invoice**.")

uploaded_file = st.file_uploader("Upload File (PDF/Image)", type=["jpg", "png", "pdf"])

if uploaded_file:
    if uploaded_file.type == "application/pdf":
        st.info(f"📄 PDF Loaded: {uploaded_file.name}")
    else:
        st.image(uploaded_file, caption="Preview", width=300)
    
    if st.button("🚀 Analyze Now"):
        with st.spinner("🤖 AI is reading handwriting & detecting context..."):
            text = get_text_from_file(uploaded_file)
            
            # --- AUTO-DETECT TYPE ---
            # Check for Car Keywords
            car_keywords = ["Ex-Showroom", "On Road", "Hypothecation", "RTO", "Variant", "Model"]
            is_car = any(k.lower() in text.lower() for k in car_keywords)

            if is_car:
                st.success("✅ Detected: New Car Quotation")
                data = smart_parse_car_quotation(text)
                
                # Metric Row
                c1, c2, c3 = st.columns(3)
                c1.metric("Ex-Showroom", f"₹{data['ex_showroom']:,.2f}")
                c2.metric("Road Tax (RTO)", f"₹{data['life_tax']:,.2f}")
                c3.metric("On-Road Price", f"₹{data['on_road']:,.2f}", delta="Final")
                
                st.subheader("📋 Smart Cost Breakdown")
                
                # Use Tabs for cleaner look
                tab1, tab2 = st.tabs(["Essential Costs", "Extras & Accessories"])
                
                with tab1:
                    col1, col2 = st.columns(2)
                    col1.text_input("Insurance (Zero Dep/Bumper)", value=f"₹{data['insurance']:,.2f}")
                    col1.text_input("Extended Warranty (EW)", value=f"₹{data['extended_warranty']:,.2f}")
                    col2.text_input("TCS (Tax Collected)", value=f"₹{data['tcs']:,.2f}")
                    col2.text_input("Fastag / RFID", value=f"₹{data['fastag']:,.2f}")

                with tab2:
                    col1, col2 = st.columns(2)
                    col1.text_input("Accessories / Kit", value=f"₹{data['accessories']:,.2f}")
                    col1.text_input("Value Added Services (VAS)", value=f"₹{data['vas']:,.2f}")
                    col2.text_input("Handling / Misc Charges", value=f"₹{data['others']:,.2f}")
                    col2.text_input("Temp Registration", value=f"₹{data['temp_reg']:,.2f}")

            else:
                st.success("✅ Detected: GST Invoice")
                data = parse_gst_invoice(text)
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("GSTIN", data['gstin'] or "Missing")
                c2.metric("Account No", data['account'] or "Missing")
                c3.metric("IFSC", data['ifsc'] or "Missing")
                c4.metric("Tax Type", "IGST" if data['igst'] > 0 else "Intra-State")
