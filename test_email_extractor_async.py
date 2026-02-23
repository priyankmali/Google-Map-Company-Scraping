"""
Test Async Email Extractor
Usage: python3 test_email_extractor_async.py <url>
"""

import os
import sys
import time
import pandas as pd
import requests
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from scratch_extractor_async import run_email_extraction_bs4_async


SERVICE_MENU_TERMS = ("service", "services", "our services")
SERVICE_FALLBACK_PATHS = [
    "/service",
    "/services",
    "/our-service",
    "/our-services",
    "/product",
    "/products",
    "/solutions",
    "/what-we-do",
]
HEADERS = {"User-Agent": "Mozilla/5.0"}
NOISY_PHRASES = {
    "we have the expertise",
    "you've got the questions",
    "we've got the ideal software",
    "turn your ideas",
}
GENERIC_NAV_ITEMS = {
    "home", "about", "about us", "portfolio", "contact", "contact us",
    "career", "our team", "team", "company",
    "services", "service", "our services",
    "products", "product", "our products",
}


def _clean_text(text):
    return " ".join((text or "").strip().split())


def _is_compact_service_label(text):
    lowered = text.lower()
    if len(text.split()) > 6:
        return False
    if any(p in lowered for p in NOISY_PHRASES):
        return False
    if any(ch in text for ch in [".", "?", "!", ":", ";"]):
        return False
    return True


def _extract_navbar_services_bs4(html):
    soup = BeautifulSoup(html, "html.parser")
    services = set()
    nav_scopes = soup.select("nav, header, .navbar, .main-menu, .menu, .navigation")

    for scope in nav_scopes:
        scope_text = _clean_text(scope.get_text(" ", strip=True)).lower()
        if not any(term in scope_text for term in SERVICE_MENU_TERMS):
            continue
        for item in scope.select("li a, li span, .dropdown-menu a, .sub-menu a, .mega-menu a"):
            txt = _clean_text(item.get_text(" ", strip=True))
            lowered = txt.lower()
            if not txt:
                continue
            if lowered in GENERIC_NAV_ITEMS:
                continue
            if _is_compact_service_label(txt):
                services.add(txt)
    return services


def _extract_headings_from_related_pages(base_url):
    headings = set()
    for path in SERVICE_FALLBACK_PATHS:
        try:
            url = urljoin(base_url, path)
            r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)
            if r.status_code != 200:
                continue
            ct = (r.headers.get("Content-Type") or "").lower()
            if "text/html" not in ct and "application/xhtml+xml" not in ct:
                continue
            soup = BeautifulSoup(r.text, "html.parser")
            for tag_name in ["h1", "h2", "h3", "h4", "h5", "h6"]:
                for tag in soup.find_all(tag_name):
                    txt = _clean_text(tag.get_text(" ", strip=True))
                    if txt:
                        headings.add(txt)
        except Exception:
            continue
    return headings


def extract_services_test_strategy(website):
    """
    Strategy:
    1) Try services list from navbar/menu first.
       - static HTML parse
       - then Selenium hover/click parse
    2) If still empty, visit /service|/services|/product|... pages and collect heading tags.
    """
    # Step 1A: BS4 static navbar
    navbar_services = set()
    try:
        r = requests.get(website, headers=HEADERS, timeout=15, allow_redirects=True)
        if r.status_code == 200:
            navbar_services = _extract_navbar_services_bs4(r.text)
    except Exception:
        pass

    # Step 1B: Selenium navbar hover/click path
    if not navbar_services:
        try:
            from selenium_extractor import extract_emails_and_services_with_selenium
            _, sel_services = extract_emails_and_services_with_selenium(website)
            for s in sel_services:
                cleaned = _clean_text(s)
                if cleaned:
                    navbar_services.add(cleaned)
        except Exception:
            pass

    if navbar_services:
        return sorted(navbar_services), "navbar"

    # Step 2: fallback to related pages and collect all heading tags.
    heading_services = _extract_headings_from_related_pages(website)
    return sorted(heading_services), "related_pages_headings"


def test_url(url):
    print(f"Testing URL (async): {url}")
    print("-" * 50)

    normalized_url = url.strip()
    if normalized_url.startswith("http://"):
        normalized_url = "https://" + normalized_url[len("http://"):]

    df = pd.DataFrame(
        [
            {
                "name": "Test Company",
                "address": None,
                "phone": None,
                "website": normalized_url,
            }
        ]
    )

    start_time = time.time()
    result_df = run_email_extraction_bs4_async(
        df,
        retry_no_emails_with_selenium=True,
        retry_no_services_with_selenium=True,
        include_debug_columns=True,
    )
    duration = time.time() - start_time

    if result_df.empty:
        emails = None
        phone = None
        services = None
        status = "no_emails"
    else:
        row = result_df.iloc[0].to_dict()
        emails = row.get("emails")
        phone = row.get("phone")
        services = row.get("services")
        services_source = row.get("services_source")
        status = row.get("status")
        if status is None:
            has_email = bool(str(emails).strip()) if emails is not None else False
            has_phone = bool(str(phone).strip()) if phone is not None else False
            if has_email and has_phone:
                status = "success"
            elif has_email:
                status = "success"
            elif has_phone:
                status = "no_emails"
            else:
                status = "no_contact_info"
    strategy_services, strategy_source = extract_services_test_strategy(normalized_url)

    print(f"Time Taken: {duration:.2f} seconds")
    print(f"Status: {status}")
    print(f"Emails: {emails}")
    print(f"Phones: {phone}")
    print(f"Services: {services}")
    if services_source is not None:
        print(f"Services Source: {services_source}")
    print(f"Services Strategy Source: {strategy_source}")
    print(f"Services Strategy Count: {len(strategy_services)}")
    if strategy_services:
        print("Services Strategy List:")
        for s in strategy_services:
            print(f"  - {s}")
    print("-" * 50)


def test_excel_async(
    excel_path="we.xlsx",
    per_site_timeout=45,
    homepage_timeout=20,
    max_rows=None,
    max_concurrent_sites=20,
    selenium_fallback=False,
    fallback_if_phones_found=True,
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
        f"selenium_fallback={selenium_fallback}, "
        f"fallback_if_phones_found={fallback_if_phones_found}"
    )
    print("-" * 50)

    def progress_callback(progress):
        print(f"Progress: {progress * 100:.1f}%")

    start_time = time.time()
    result_df = run_email_extraction_bs4_async(
        df,
        progress_callback=progress_callback,
        max_concurrent_sites=max_concurrent_sites,
        request_timeout=homepage_timeout,
        retry_no_emails_with_selenium=selenium_fallback,
        retry_no_services_with_selenium=selenium_fallback,
        include_debug_columns=True,
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
    services_found = 0
    no_services = 0
    if "services" in result_df.columns:
        services_found = int(result_df["services"].fillna("").astype(str).str.strip().ne("").sum())
        no_services = int(len(result_df) - services_found)
    elif "service_count" in result_df.columns:
        services_found = int((result_df["service_count"].fillna(0) > 0).sum())
        no_services = int(len(result_df) - services_found)

    print("\n" + "=" * 60)
    print(f"Completed {len(result_df)} rows in {duration:.2f}s")
    print(f"Success: {success}")
    print(f"Homepage Timeout: {home_timeout}")
    print(f"Timeout: {timeout}")
    print(f"No Emails: {no_emails}")
    print(f"No Contact Info: {no_contact}")
    print(f"No Website: {no_website}")
    print(f"Services Found: {services_found}")
    print(f"No Services: {no_services}")
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
    # python3 test_email_extractor_async.py we.xlsx 45 20 50 10 false true
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".xlsx"):
        excel_path = sys.argv[1]
        per_site_timeout = int(sys.argv[2]) if len(sys.argv) > 2 else 45
        homepage_timeout = int(sys.argv[3]) if len(sys.argv) > 3 else 20
        max_rows = int(sys.argv[4]) if len(sys.argv) > 4 else None
        max_concurrent_sites = int(sys.argv[5]) if len(sys.argv) > 5 else 20
        selenium_fallback = (sys.argv[6].lower() == "true") if len(sys.argv) > 6 else False
        fallback_if_phones_found = (sys.argv[7].lower() == "true") if len(sys.argv) > 7 else True
        test_excel_async(
            excel_path=excel_path,
            per_site_timeout=per_site_timeout,
            homepage_timeout=homepage_timeout,
            max_rows=max_rows,
            max_concurrent_sites=max_concurrent_sites,
            selenium_fallback=selenium_fallback,
            fallback_if_phones_found=fallback_if_phones_found,
        )
    elif len(sys.argv) > 1:
        test_url(sys.argv[1])
    else:
        test_excel_async("we.xlsx")
