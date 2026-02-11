def smart_parse_car_quotation(text):
    """
    Extracts car fields using Synonyms & Context Mapping.
    Updated to handle Multi-line tables and Toyota-specific terms.
    """
    data = {}
    
    # A. The "Dictionary" of Contexts (Updated for Toyota & Multi-line docs)
    context_map = {
        'ex_showroom': ["Ex-Showroom", "Basic Price", "Unit Cost", "Vehicle Cost", "Showroom Price"],
        'tcs': ["TCS", "Tax Collected", "Income Tax", "1% Tax", "Tax @1%"],
        'life_tax': ["Life Tax", "Road Tax", "RTO", "Perm Registration", "Regn Charges", "Perm Reg"],
        'fastag': ["Fastag", "Fast Tag", "Tag Cost", "RFID"],
        'temp_reg': ["Temp", "Temporary", "TR Charges", "Tmp Reg"],
        
        'insurance': ["Insurance", "Comprehensive", "OD Premium", "Bumper to Bumper", "Zero Dep"],
        'extended_warranty': ["Extended Warranty", "Ext Warranty", "EW", "Shield", "T Secure", "Protection Plan"],
        'rsa': ["RSA", "Roadside", "Assistance"],
        
        'accessories': ["Accessories", "Kit", "Fitting", "Acc.", "Mud Flap", "Mats", "Basic Kit"],
        'vas': ["VAS", "Value Added", "Coating", "Teflon", "Anti Rust", "Smiles"],
        'others': ["Others", "Misc", "Handling", "Logistics", "Depot Charges", "H.C."],
        
        'on_road': ["On Road", "Total", "Net Amount", "Grand Total", "Final Price", "To Pay", "Amount in Rs"]
    }

    def extract_value_smart(field_key):
        """
        Scans text for keywords and grabs the nearest number, 
        EVEN IF it is on the next line.
        """
        keywords = context_map.get(field_key, [])
        
        # Regex Explanation:
        # 1. (?: ... ) -> Match any of the keywords (Case Insensitive)
        # 2. [\s\S]{0,60}? -> Scan the next 0 to 60 characters (across newlines!)
        # 3. ([\d,]+\.\d{2}) -> Capture a number that specifically ends in .00 (Currency format)
        
        pattern = rf"(?:{'|'.join(keywords)})[\s\S]{{0,60}}?([\d,]+\.\d{{2}})"
        
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            # Clean string (remove commas) to make it a number
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
