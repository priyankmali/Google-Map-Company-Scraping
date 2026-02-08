"""
Email and Phone Number Extractor Module

This module handles the extraction of emails and phone numbers from websites.
"""

import re
import requests
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed


# Email and Phone regex
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

# Phone number regex - supports multiple formats
PHONE_REGEX = re.compile(
    r"(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{1,4}\)?[-.\s]?)?\d{1,4}[-.\s]?\d{1,4}[-.\s]?\d{1,9}"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


def extract_emails_and_phones_from_site(website):
    """
    Extract emails and phone numbers from a website
    
    Args:
        website: URL of the website to scrape
    
    Returns:
        Tuple of (emails_list, phones_list)
    """
    emails = set()
    phones = set()
    
    # Expanded list of common contact pages
    paths = [
        "",           # Homepage
        "/contact",   # Contact page
        "/contact-us",
        "/contactus",
        "/about",     # About page
        "/about-us",
        "/get-in-touch",
        "/reach-us",
        "/team"
    ]

    for path in paths:
        try:
            url = urljoin(website, path)
            r = requests.get(url, headers=HEADERS, timeout=15, allow_redirects=True)

            if r.status_code != 200:
                continue

            # Extract emails
            found_emails = EMAIL_REGEX.findall(r.text)
            for email in found_emails:
                # Filter out image files and common false positives
                if not email.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
                    # Avoid generic/placeholder emails
                    if not any(x in email.lower() for x in ["example.com", "test@", "noreply@"]):
                        emails.add(email)
            
            # Extract phone numbers
            found_phones = PHONE_REGEX.findall(r.text)
            for phone in found_phones:
                # Clean and validate phone number
                phone_clean = phone.strip()
                # Only keep if it looks like a valid phone (at least 7 digits)
                digits_only = re.sub(r"\D", "", phone_clean)
                if 7 <= len(digits_only) <= 15:  # Valid phone number range
                    phones.add(phone_clean)

        except Exception as e:
            continue

    return list(emails), list(phones)


def email_phone_worker(row):
    """
    Worker function to extract emails and phones for a single company
    
    Args:
        row: Dictionary/Series with company data including 'website' and 'phone'
    
    Returns:
        Dictionary with extracted data
    """
    result = {
        "name": row.get("name"),
        "address": row.get("address"),
        "phone": row.get("phone"),  # Phone from Google Maps
        "website": row.get("website"),
        "emails": None,
        "status": "success"
    }

    website = row.get("website")

    if not isinstance(website, str) or not website.startswith("http"):
        result["status"] = "no_website"
        return result

    emails, scraped_phones = extract_emails_and_phones_from_site(website)

    if emails:
        result["emails"] = ", ".join(emails)
    
    # Combine Google Maps phone and scraped phones
    all_phones = set()
    
    # Add Google Maps phone if exists
    gmaps_phone = row.get("phone")
    if gmaps_phone and isinstance(gmaps_phone, str):
        all_phones.add(gmaps_phone.strip())
    
    # Add scraped phones
    if scraped_phones:
        for phone in scraped_phones:
            all_phones.add(phone.strip())
    
    # Update phone field with combined phones
    if all_phones:
        result["phone"] = ", ".join(sorted(all_phones))
    
    if not emails and not all_phones:
        result["status"] = "no_contact_info"
    elif not emails:
        result["status"] = "no_emails"

    return result


def run_email_extraction(df_input, progress_callback=None, status_callback=None):
    """
    Extract emails and phone numbers for all companies in the dataframe
    
    Args:
        df_input: DataFrame with company data including 'website' column
        progress_callback: Function to call with progress (0.0 to 1.0)
        status_callback: Function to call with status text
    
    Returns:
        DataFrame with extracted emails and phone numbers
    """
    import pandas as pd
    
    total = len(df_input)
    results = []
    workers = 20  # Increased parallel workers for email extraction

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(email_phone_worker, row): idx
            for idx, row in df_input.iterrows()
        }

        completed = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            
            completed += 1
            
            # Update progress
            if progress_callback:
                progress_callback(completed / total)
            
            # Update status
            if status_callback:
                name = result.get("name") or "Unknown Company"
                emails = result.get("emails")
                phones = result.get("phone")
                
                if emails and phones:
                    status_callback(f"✅ {name} → Emails: {emails} | Phones: {phones}")
                elif emails:
                    status_callback(f"✅ {name} → Emails: {emails}")
                elif phones:
                    status_callback(f"✅ {name} → Phones: {phones}")
                else:
                    status_callback(f"⚠️ {name} → No contact info found")

    return pd.DataFrame(results)
