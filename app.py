import streamlit as st
import os
import json

# --- CONFIGURATION ---
st.set_page_config(page_title="Invoice Scanner", page_icon="🧾")

# --- 1. SMART SETUP (FIXES MALFORMED KEYS) ---
# Check if we are in the cloud
if "google_credentials" in st.secrets:
    # 1. Get the JSON data from secrets
    secret_data = st.secrets["google_credentials"]["json_data"]
    
    # 2. Parse it into a Python dictionary
    try:
        if isinstance(secret_data, str):
            creds_dict = json.loads(secret_data)
        else:
            creds_dict = dict(secret_data)
            
        # 3. CRITICAL FIX: Repair the Private Key format
        # The key needs real newlines (\n), but sometimes they get pasted as literals (\\n)
        if "private_key" in creds_dict:
            creds_dict["private_key"] = creds_dict["private_key"].replace("\\n", "\n")

        # 4. Save the repaired JSON to a file
        with open("service_account.json", "w") as f:
            json.dump(creds_dict, f)
            
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"
        
    except json.JSONDecodeError:
        st.error("❌ Error: The Secret Key in Streamlit settings is not valid JSON.")
        st.stop()

# Check if we are local
elif os.path.exists("service_account.json"):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "service_account.json"

else:
    st.error("❌ Critical Error: Google Credentials not found.")
    st.stop()

# --- 2. IMPORT LIBRARIES SAFELY ---
try:
    from google.cloud import vision
    import fitz  # This is PyMuPDF
except ImportError as e:
    st.error(f"❌ Missing Library: {e}")
    st.info("Run this command in terminal: pip install google-cloud-vision pymupdf")
    st.stop()

# --- 3. HELPER FUNCTIONS ---
def get_text_from_file(uploaded_file):
    """
    Reads text from Image OR PDF using Google Cloud Vision.
    """
    client = vision.ImageAnnotatorClient()
    content = uploaded_file.getvalue()
    image = None

    # HANDLE PDF
    if uploaded_file.type == "application/pdf":
        try:
            # Convert PDF Page 1 to Image
            doc = fitz.open(stream=content, filetype="pdf")
            page = doc.load_page(0)  # Get first page
            pix = page.get_pixmap()
            img_bytes = pix.tobytes("png")
            image = vision.Image(content=img_bytes)
            st.success("✅ PDF loaded successfully (Page 1)")
        except Exception as e:
            st.error(f"Error reading PDF: {e}")
            return ""
    # HANDLE IMAGES
    else:
        image = vision.Image(content=content)
    
    # Send to Google Cloud Vision
    response = client.document_text_detection(image=image)
    return response.full_text_annotation.text

def extract_details(text):
    """
    Extracts GST, Account, and Amounts using Regex.
    """
    data = {}
    
    # GSTIN
    gst_match = re.search(r"\d{2}[A-Z]{5}\d{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}", text)
    data['gstin'] = gst_match.group(0) if gst_match else None

    # Account Number
    acc_match = re.search(r"(?:Account|Acc|A/c)[^0-9]*(\d{9,18})", text, re.IGNORECASE)
    data['account'] = acc_match.group(1) if acc_match else None

    # Amounts
    def find_amount(label):
        match = re.search(rf"{label}[^\d]*([\d,]+\.\d{{2}})", text, re.IGNORECASE)
        if match:
             return float(match.group(1).replace(",", ""))
        return 0.0

    data['cgst'] = find_amount("CGST")
    data['sgst'] = find_amount("SGST")
    data['igst'] = find_amount("IGST")
    
    return data

# --- 4. APP UI ---
st.title("🧾 Invoice Validator AI")
st.write("Upload Digital, Scanned, or Handwritten Invoices")

# THIS IS THE KEY LINE FOR PDF BROWSING:
uploaded_file = st.file_uploader("Choose an invoice...", type=["jpg", "png", "jpeg", "pdf"])

if uploaded_file is not None:
    
    # Display Preview
    if uploaded_file.type == "application/pdf":
        st.info(f"📄 File Selected: {uploaded_file.name}")
    else:
        st.image(uploaded_file, caption="Uploaded Image", use_column_width=True)
    
    # Analyze Button
    if st.button("Analyze Invoice"):
        with st.spinner("👀 AI is reading the invoice..."):
            try:
                raw_text = get_text_from_file(uploaded_file)
                
                if raw_text:
                    data = extract_details(raw_text)

                    # RESULTS
                    st.divider()
                    st.subheader("📊 Extraction Results")
                    
                    c1, c2, c3 = st.columns(3)
                    c1.metric("GSTIN", data['gstin'] or "Not Found")
                    c2.metric("Account No", data['account'] or "Not Found")
                    c3.metric("Tax Mode", "IGST" if data['igst'] > 0 else "Intra-State")

                    st.write("---")
                    st.write(f"**CGST:** ₹{data['cgst']} | **SGST:** ₹{data['sgst']} | **IGST:** ₹{data['igst']}")

                    # LOGIC CHECK
                    if data['igst'] > 0 and (data['cgst'] > 0 or data['sgst'] > 0):
                        st.error("❌ Logic Error: Invoice contains BOTH IGST and CGST/SGST.")
                    elif data['gstin']:
                        st.success("✅ GSTIN Format Valid")
                else:
                    st.warning("Could not extract text. Please try a clearer image.")

            except Exception as e:
                st.error(f"An error occurred: {e}")
