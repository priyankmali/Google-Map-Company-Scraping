"""
Google Maps Scraper - Complete Pipeline
Main Streamlit Application
"""

import streamlit as st
from multiprocessing import Pool
import pandas as pd
import io

# Import our custom modules
from details_extractor import scrape_single_location, run_detail_extraction
from email_extractor_async import run_email_extraction_async


st.set_page_config(page_title="Google Maps Scraper", layout="wide")
st.markdown(
    "<h1>Google Maps Scraper -<span style='color:yellow;'> KOLI INFOTECH</span></h1>",
    unsafe_allow_html=True
)

# Initialize session state
if 'scraped_data' not in st.session_state:
    st.session_state.scraped_data = None
if 'detailed_data' not in st.session_state:
    st.session_state.detailed_data = None
if 'email_data' not in st.session_state:
    st.session_state.email_data = None

# Create tabs for better organization
tab1, tab2 = st.tabs(["📤 Upload Excel for Email Extraction", "🗺️ Scrape from Google Maps"])

with tab1:
    st.write("### Upload your company details Excel file to extract emails directly")
    st.write("Your Excel file should contain columns like: name, address, phone, website")
    
with tab2:
    st.write("### Start fresh by scraping companies from Google Maps")
    keyword = st.text_input("Business keyword", "Software company")
    place_input = st.text_input("Location", "Surat")


# ================= MAIN SCRAPER =================
def run_scraper_parallel():
    """Scrape Google Maps for company URLs"""
    try:
        locations = [l.strip() for l in place_input.split(",") if l.strip()]
        tasks = [(keyword, loc) for loc in locations]

        workers = min(3, len(tasks))
        
        st.write(f"🔍 Finding company in {place_input}")

        with Pool(processes=workers) as pool:
            results = pool.map(scrape_single_location, tasks)

        global_places = set()
        all_records = []

        for location_records in results:
            for r in location_records:
                if r["place_url"] not in global_places:
                    global_places.add(r["place_url"])
                    all_records.append(r)

        st.success("✅ Search completed")

        df = pd.DataFrame(all_records)
        st.session_state.scraped_data = df

        st.write("### 📊 Summary")
        st.write("Total Company Found:", len(global_places))

    except Exception as e:
        st.error(str(e))


# ================= DETAIL EXTRACTION WRAPPER =================
def run_detail_extraction_ui():
    """UI wrapper for detail extraction"""
    if st.session_state.scraped_data is None:
        st.error("❌ No scraped data found. Please run 'Start Scraping' first.")
        return

    df_places = st.session_state.scraped_data
    total_places = len(df_places)

    st.info(f"🔍 Extracting details for {total_places} companies...")
    st.success("⚡ processing extraction!")

    progress = st.progress(0)
    status_text = st.empty()
    
    # Run extraction with callbacks
    df_detailed = run_detail_extraction(
        df_places,
        progress_callback=lambda p: progress.progress(p),
        status_callback=lambda s: status_text.text(s)
    )
    
    # Filter out companies with no website
    if df_detailed is not None and not df_detailed.empty:
        # Remove None, NaN, and empty strings
        df_detailed = df_detailed[df_detailed['website'].notna() & (df_detailed['website'] != "")]
        
        # Display filtering result
        removed_count = total_places - len(df_detailed)
        if removed_count > 0:
            st.warning(f"⚠️ Filtered out {removed_count} companies with no website.")
        st.success(f"✅ Retained {len(df_detailed)} companies with websites.")
    
    st.session_state.detailed_data = df_detailed

    st.success("✅ Detail extraction completed!")

    st.write("### 📋 Extracted Company Details")
    st.dataframe(
        df_detailed[['name', 'address', 'phone', 'website']],
        width="stretch",
        hide_index=True
    )


# ================= EMAIL EXTRACTION WRAPPER =================
def run_email_extraction_ui(df_input):
    """UI wrapper for email extraction"""
    total = len(df_input)
    st.info(f"⚡ Extracting emails and phone numbers from {total} websites...")

    progress = st.progress(0)
    status_text = st.empty()
    
    # Run async extraction directly with default production settings.
    df_emails = run_email_extraction_async(
        df_input,
        progress_callback=lambda p: progress.progress(p),
        status_callback=lambda s: status_text.text(s),
        max_concurrent_sites=15,
        max_connections=60,
        request_timeout=10,
        per_site_timeout=40,
        homepage_timeout=20,
        max_concurrent_selenium_fallbacks=2,
        selenium_timeout=10,
        selenium_fallback=False
    )
    
    st.session_state.email_data = df_emails

    st.success("✅ Email and phone extraction completed!")

    st.write("### 📧 Companies with Contact Information")
    st.dataframe(
        df_emails,
        width="stretch",
        hide_index=True
    )


# ================= UPLOAD SECTION (IN TAB1) =================
with tab1:
    uploaded_file = st.file_uploader("Upload Excel file with company details", type=['xlsx', 'xls'], key="upload_main")
    
    if uploaded_file is not None:
        df_uploaded = pd.read_excel(uploaded_file)
        st.write("**Uploaded file preview:**")
        st.dataframe(df_uploaded.head(), width="stretch")
        
        if st.button("🚀 Extract Emails from Uploaded File"):
            run_email_extraction_ui(df_uploaded)

# ================= BUTTONS IN TAB2 =================
with tab2:
    if st.button("Start Scraping"):
        run_scraper_parallel()

# Show detail extraction button only if data is scraped
with tab2:
    if st.session_state.scraped_data is not None:
        if st.button("Start Extracting Details"):
            run_detail_extraction_ui()

# Show download button only if details are extracted
with tab2:
    if st.session_state.detailed_data is not None:
        df_download = st.session_state.detailed_data[['name', 'address', 'phone', 'website']]
        
        # Create Excel file in memory
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df_download.to_excel(writer, index=False, sheet_name='Company Details')
        
        excel_data = output.getvalue()
        
        st.download_button(
            label="📥 Download Company Details (Excel)",
            data=excel_data,
            file_name="company_details.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        
        st.write("---")
        st.write("### 📧 Email Extraction")
        
        # Extract emails from current data
        if st.button("🚀 Extract Emails from Current Data"):
            run_email_extraction_ui(st.session_state.detailed_data)

# Show email download button if emails are extracted
if st.session_state.email_data is not None:
    output_email = io.BytesIO()
    with pd.ExcelWriter(output_email, engine='openpyxl') as writer:
        st.session_state.email_data.to_excel(writer, index=False, sheet_name='Companies with Emails')
    
    email_excel_data = output_email.getvalue()
    
    st.download_button(
        label="📥 Download Companies with Emails (Excel)",
        data=email_excel_data,
        file_name="companies_with_emails.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
