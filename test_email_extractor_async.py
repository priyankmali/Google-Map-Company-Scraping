"""
Test Async Email Extractor
Usage: python3 test_email_extractor_async.py <url>
"""

import os
import sys
import time
import pandas as pd

from email_extractor_async import run_email_extraction_async


def test_url(url):
    print(f"Testing URL (async): {url}")
    print("-" * 50)

    df = pd.DataFrame(
        [
            {
                "name": "Test Company",
                "address": None,
                "phone": None,
                "website": url,
            }
        ]
    )

    start_time = time.time()
    result_df = run_email_extraction_async(df)
    duration = time.time() - start_time

    row = result_df.iloc[0].to_dict()
    emails = row.get("emails")
    phone = row.get("phone")
    status = row.get("status")

    print(f"Time Taken: {duration:.2f} seconds")
    print(f"Status: {status}")
    print(f"Emails: {emails}")
    print(f"Phones: {phone}")
    print("-" * 50)


def test_excel_async(
    excel_path="we.xlsx",
    per_site_timeout=45,
    homepage_timeout=20,
    max_rows=None,
    max_concurrent_sites=20,
    selenium_fallback=False,
):
    """
    Run async extraction for all websites in an Excel file.
    """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    df = pd.read_excel(excel_path)
    if "website" not in df.columns:
        raise ValueError("Excel must contain a 'website' column")

    if max_rows is not None:
        df = df.head(max_rows)

    print(f"Testing async extraction for {len(df)} rows from: {excel_path}")
    print(
        f"Settings -> per_site_timeout={per_site_timeout}s, "
        f"homepage_timeout={homepage_timeout}s, "
        f"max_concurrent_sites={max_concurrent_sites}, "
        f"selenium_fallback={selenium_fallback}"
    )
    print("-" * 50)

    def progress_callback(progress):
        print(f"Progress: {progress * 100:.1f}%")

    start_time = time.time()
    result_df = run_email_extraction_async(
        df,
        progress_callback=progress_callback,
        per_site_timeout=per_site_timeout,
        homepage_timeout=homepage_timeout,
        max_concurrent_sites=max_concurrent_sites,
        selenium_fallback=selenium_fallback,
    )
    duration = time.time() - start_time

    output_path = "we_async_extraction_test_results.xlsx"
    result_df.to_excel(output_path, index=False)

    success = (result_df["status"] == "success").sum() if "status" in result_df.columns else 0
    timeout = (result_df["status"] == "timeout").sum() if "status" in result_df.columns else 0
    home_timeout = (
        (result_df["status"] == "home_timeout").sum()
        if "status" in result_df.columns else 0
    )
    no_emails = (result_df["status"] == "no_emails").sum() if "status" in result_df.columns else 0
    no_contact = (
        (result_df["status"] == "no_contact_info").sum()
        if "status" in result_df.columns else 0
    )
    no_website = (
        (result_df["status"] == "no_website").sum()
        if "status" in result_df.columns else 0
    )
    selenium_used = (
        int(result_df["selenium_fallback_used"].fillna(False).sum())
        if "selenium_fallback_used" in result_df.columns else 0
    )

    print("\n" + "=" * 60)
    print(f"Completed {len(result_df)} rows in {duration:.2f}s")
    print(f"Success: {success}")
    print(f"Homepage Timeout: {home_timeout}")
    print(f"Timeout: {timeout}")
    print(f"No Emails: {no_emails}")
    print(f"No Contact Info: {no_contact}")
    print(f"No Website: {no_website}")
    print(f"Selenium Fallback Used: {selenium_used}")
    print(f"Saved results to: {output_path}")
    if "duration_sec" in result_df.columns and not result_df.empty:
        print("\nTop 10 slow rows:")
        slow = result_df.sort_values("duration_sec", ascending=False).head(10)
        cols = [c for c in ["name", "website", "status", "duration_sec", "selenium_fallback_used"] if c in slow.columns]
        print(slow[cols].to_string(index=False))
    print("=" * 60)


if __name__ == "__main__":
    # Usage examples:
    # python3 test_email_extractor_async.py https://example.com
    # python3 test_email_extractor_async.py we.xlsx
    # python3 test_email_extractor_async.py we.xlsx 45 20 50 10 false
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".xlsx"):
        excel_path = sys.argv[1]
        per_site_timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 45
        homepage_timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        max_rows = int(sys.argv[4]) if len(sys.argv) > 4 else None
        max_concurrent_sites = int(sys.argv[5]) if len(sys.argv) > 5 else 20
        selenium_fallback = (sys.argv[6].lower() == "true") if len(sys.argv) > 6 else False
        test_excel_async(
            excel_path=excel_path,
            per_site_timeout=per_site_timeout,
            homepage_timeout=homepage_timeout,
            max_rows=max_rows,
            max_concurrent_sites=max_concurrent_sites,
            selenium_fallback=selenium_fallback,
        )
    elif len(sys.argv) > 1:
        test_url(sys.argv[1])
    else:
        test_excel_async("we.xlsx")
