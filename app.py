"""
Company Scraper - Complete Pipeline
Main Streamlit Application
"""

import streamlit as st
from multiprocessing import Pool
import pandas as pd
import io
import time
import threading
import re
from concurrent.futures import ThreadPoolExecutor

# Import our custom modules
from details_extractor import scrape_single_location, run_detail_extraction
from scratch_extractor_async import run_email_extraction_bs4_async

EMAIL_EXECUTOR = ThreadPoolExecutor(max_workers=1)

st.set_page_config(page_title="Ventexa: Business Data Extractor", layout="wide")
st.markdown(
    "<h1>Business Data Extractor -<span style='color:#4FE7C0;'> VENTEXA</span></h1>",
    unsafe_allow_html=True
)

# Initialize session state
if 'scraped_data' not in st.session_state:
    st.session_state.scraped_data = None
if 'detailed_data' not in st.session_state:
    st.session_state.detailed_data = None
if 'email_data' not in st.session_state:
    st.session_state.email_data = None
if 'email_job' not in st.session_state:
    st.session_state.email_job = None

# Create tabs for better organization
tab1, tab2 = st.tabs(["📤 Upload Excel for Email Extraction", "🗺️ Scrape Companies"])

with tab1:
    st.write("### Upload your company details Excel file to extract emails directly")
    st.write("Your Excel file should contain columns like: name, address, phone, website")
    
with tab2:
    st.write("### Data Extractor Form")
    keyword = st.text_input("Business keyword", "IT Software company")
    place_input = st.text_input("Location", "Ontario")


# ================= MAIN SCRAPER =================
def run_scraper_parallel():
    """Scrape company URLs"""
    try:
        locations = [l.strip() for l in place_input.split(",") if l.strip()]
        if not locations:
            st.warning("Please enter at least one valid location.")
            return

        tasks = [(keyword, loc) for loc in locations]
        workers = min(3, len(tasks))
        progress = st.progress(0)
        status_text = st.empty()
        status_text.info(f"🔍 Starting scrape for {len(tasks)} location(s)...")
        
        results = []
        with st.spinner("Scraping companies... this may take some time"):
            with Pool(processes=workers) as pool:
                for completed, location_records in enumerate(
                    pool.imap_unordered(scrape_single_location, tasks),
                    start=1
                ):
                    results.append(location_records)
                    progress.progress(completed / len(tasks))
                    status_text.info(f"🔄 Processed {completed}/{len(tasks)} location(s)")

        global_places = set()
        all_records = []

        for location_records in results:
            for r in location_records:
                if r["place_url"] not in global_places:
                    global_places.add(r["place_url"])
                    all_records.append(r)

        status_text.success("✅ Scraping completed")
        progress.progress(1.0)

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


def _build_smart_extractor_config(total):
    """Single smart profile tuned by batch size."""
    if total >= 1000:
        return {
            "chunk_size": 50,
            "max_concurrent_sites": 36,
            "max_connections": 180,
            "request_timeout": 12,
            "retry_no_emails_with_selenium": True,
            "max_selenium_retry_concurrent_sites": 14,
            "retry_no_services_with_selenium": True,
            "max_selenium_service_retry_concurrent_sites": 8,
            "stop_on_first_email": False,
            "include_debug_columns": False,
        }
    if total >= 500:
        return {
            "chunk_size": 40,
            "max_concurrent_sites": 30,
            "max_connections": 140,
            "request_timeout": 12,
            "retry_no_emails_with_selenium": True,
            "max_selenium_retry_concurrent_sites": 12,
            "retry_no_services_with_selenium": True,
            "max_selenium_service_retry_concurrent_sites": 6,
            "stop_on_first_email": False,
            "include_debug_columns": False,
        }
    return {
        "chunk_size": 30,
        "max_concurrent_sites": 24,
        "max_connections": 100,
        "request_timeout": 12,
        "retry_no_emails_with_selenium": True,
        "max_selenium_retry_concurrent_sites": 10,
        "retry_no_services_with_selenium": True,
        "max_selenium_service_retry_concurrent_sites": 6,
        "stop_on_first_email": False,
        "include_debug_columns": False,
    }


def _format_company_status(raw_message):
    msg = raw_message.strip()
    if "->" in msg:
        name = msg.split("->", 1)[0].strip()
    else:
        name = msg
    lowered = msg.lower()
    if any(x in lowered for x in ["timeout", "request_failed", "invalid_website", "no_emails"]):
        return f"⚠️ {name}"
    return f"✅ {name}"


def _run_email_extraction_worker(df_input, job_state, lock, extractor_config):
    total = len(df_input)
    counter = {"done": 0}

    def on_progress(p):
        with lock:
            job_state["progress"] = max(0.0, min(1.0, float(p)))

    def on_status(message):
        is_retry_stage = message.startswith("[retry-stage]")
        is_retry_row = message.startswith("[retry ")

        if is_retry_stage:
            match = re.search(r"Retrying\s+(\d+)", message)
            with lock:
                job_state["retry_done"] = 0
                job_state["retry_total"] = int(match.group(1)) if match else 0
                job_state["last_status"] = f"🔄 {message.replace('[retry-stage] ', '')}"
            return

        if is_retry_row:
            close_idx = message.find("]")
            retry_prefix = message[:close_idx + 1] if close_idx != -1 else "[retry]"
            retry_msg = message[close_idx + 2:] if close_idx != -1 else message
            match = re.match(r"\[retry\s+(\d+)/(\d+)\]", retry_prefix)
            with lock:
                if match:
                    job_state["retry_done"] = int(match.group(1))
                    job_state["retry_total"] = int(match.group(2))
                job_state["last_status"] = f"🔄 {retry_prefix} {_format_company_status(retry_msg)}"
            return

        if not is_retry_stage and not is_retry_row:
            counter["done"] = min(counter["done"] + 1, total)
            with lock:
                job_state["done"] = counter["done"]
                job_state["last_status"] = f"{counter['done']}/{total} {_format_company_status(message)}"

    return run_email_extraction_bs4_async(
        df_input,
        progress_callback=on_progress,
        status_callback=on_status,
        **extractor_config,
    )


def start_email_extraction_job(df_input, source_label):
    if df_input is None or len(df_input) == 0:
        st.warning("No input data available for email extraction.")
        return

    existing_job = st.session_state.email_job
    if existing_job and existing_job.get("state") == "running":
        st.warning("An extraction job is already running.")
        return

    total = len(df_input)
    config = _build_smart_extractor_config(total)
    job_lock = threading.Lock()
    job_state = {
        "state": "running",
        "source": source_label,
        "total": total,
        "done": 0,
        "retry_done": 0,
        "retry_total": 0,
        "progress": 0.0,
        "last_status": f"Starting smart extraction for {total} websites...",
        "started_at": time.time(),
        "finished_at": None,
        "lock": job_lock,
    }

    future = EMAIL_EXECUTOR.submit(
        _run_email_extraction_worker,
        df_input.copy(),
        job_state,
        job_lock,
        config,
    )
    job_state["future"] = future
    st.session_state.email_job = job_state


def render_email_job_status():
    job = st.session_state.email_job
    if not job:
        return

    lock = job["lock"]
    future = job["future"]

    if job["state"] == "running" and future.done():
        try:
            result = future.result()
            with lock:
                job["state"] = "done"
                job["progress"] = 1.0
                job["done"] = job["total"]
                job["last_status"] = "✅ Extraction completed."
                job["finished_at"] = time.time()
            st.session_state.email_data = result
        except Exception as exc:
            with lock:
                job["state"] = "failed"
                job["last_status"] = f"❌ Extraction failed: {exc}"
                job["finished_at"] = time.time()

    with lock:
        state = job["state"]
        progress = job["progress"]
        done = job["done"]
        total = job["total"]
        retry_done = job.get("retry_done", 0)
        retry_total = job.get("retry_total", 0)
        last_status = job["last_status"]
        started_at = job["started_at"]

    st.write("---")
    st.write("### ⚙️ Smart Extraction Job")
    if state == "running":
        if retry_total > 0:
            st.info(f"Running: {done}/{total} | Retry: {retry_done}/{retry_total}")
        else:
            st.info(f"Running: {done}/{total}")
    elif state == "done":
        if retry_total > 0:
            st.success(f"Completed: {done}/{total} | Retry: {retry_done}/{retry_total}")
        else:
            st.success(f"Completed: {done}/{total}")
    else:
        st.error(last_status)

    st.progress(progress)
    st.caption(last_status)
    elapsed = int(time.time() - started_at)
    st.caption(f"Elapsed: {elapsed}s")

    if state == "running":
        if hasattr(st, "autorefresh"):
            st.autorefresh(interval=2000, key="smart_job_refresh")
        else:
            time.sleep(2)
            if hasattr(st, "rerun"):
                st.rerun()
            else:
                st.experimental_rerun()


# ================= UPLOAD SECTION (IN TAB1) =================
with tab1:
    uploaded_file = st.file_uploader("Upload Excel file with company details", type=['xlsx', 'xls'], key="upload_main")
    
    if uploaded_file is not None:
        df_uploaded = pd.read_excel(uploaded_file)
        st.write("**Uploaded file preview:**")
        preview_df = df_uploaded.head().copy()
        preview_df.index = preview_df.index + 1
        st.dataframe(preview_df, width="stretch")
        
        if st.button("🚀 Extract Emails from Uploaded File"):
            start_email_extraction_job(df_uploaded, source_label="uploaded_file")

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
            start_email_extraction_job(st.session_state.detailed_data, source_label="current_data")

# Show current smart extraction job status
render_email_job_status()

# Show email download button if emails are extracted
if st.session_state.email_data is not None:
    st.write("---")
    st.write("### 📧 Extracted Company Contacts")
    st.dataframe(
        st.session_state.email_data,
        width="stretch",
        hide_index=True
    )

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
