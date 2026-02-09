
"""
Selenium Email and Phone Number Extractor Module
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import BoundedSemaphore
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from urllib.parse import urljoin

# Email and Phone regex (Copied from email_extractor.py to be standalone)
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

PHONE_REGEX = re.compile(
    r"""
    # Optional international prefix (+ followed by 1-3 digits)
    (?:(?:\+|00)\d{1,3}[-\s.]?)?
    
    # Optional area code in parentheses
    (?:\(?\d{2,4}\)?[-\s.]?)
    
    # First group of digits (3-4 digits)
    \d{3,4}
    
    # Separator
    [-\s.]?
    
    # Last group of digits (3-9 digits)
    \d{3,9}
    """,
    re.VERBOSE
)

# Limit concurrent Selenium instances to avoid resource exhaustion
SELENIUM_SEMAPHORE = BoundedSemaphore(3)

def _get_selenium_driver():
    """Create and return a configured Chrome driver"""
    chrome_options = Options()
    chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false") # Disable images for speed
    
    # Suppress logging
    chrome_options.add_argument("--log-level=3")
    
    service = Service(ChromeDriverManager().install())
    return webdriver.Chrome(service=service, options=chrome_options)

def extract_emails_and_phones_with_selenium(website):
    """
    Extract emails and phone numbers from a website using Selenium
    Wrapper that ensures we don't exceed max concurrent browsers
    """
    with SELENIUM_SEMAPHORE:
        return _extract_logic(website)

def _extract_logic(website):
    emails = set()
    phones = set()
    driver = None
    
    try:
        driver = _get_selenium_driver()
        
        # Common paths to check
        paths = ["", "/contact", "/contact-us", "/about", "/about-us"]
        
        for path in paths:
            try:
                url = urljoin(website, path)
                driver.get(url)
                
                # Wait a bit for JS to execute
                time.sleep(3)
                
                page_source = driver.page_source
                
                # Extract emails
                found_emails = EMAIL_REGEX.findall(page_source)
                for email in found_emails:
                    if not email.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
                        if not any(x in email.lower() for x in ["example.com", "test@", "noreply@"]):
                            emails.add(email)
                
                # Extract phone numbers
                potential_phones = re.findall(r'(?:\+?\d{1,3}[-\s.]?)?(?:\(?\d{3}\)?[-\s.]?)?\d{3}[-\s.]?\d{4,6}', page_source)
                
                for phone in potential_phones:
                    phone_clean = phone.strip()
                    if any(x in phone_clean for x in [",", ";", "<", ">", "{", "}"]):
                        continue
                    
                    # Logic to filter out bad phone numbers (same as original)
                    parts = re.split(r'[-\s.]', phone_clean)
                    parts = [p for p in parts if p.isdigit()]
                    if len(parts) == 3 and all(len(p) <= 3 for p in parts): continue
                    if phone_clean.startswith("0") and len(phone_clean) < 10: continue
                    if phone_clean.replace(" ", "").isdigit() and len(phone_clean.replace(" ", "")) < 10: continue
                    if "." in phone_clean and phone_clean.replace(".", "").isdigit():
                         if len(phone_clean.split(".")[1]) > 0: continue
                    
                    digits_only = re.sub(r"\D", "", phone_clean)
                    if 10 <= len(digits_only) <= 15:
                        if len(set(digits_only)) < 3: continue
                        phones.add(phone_clean)
                        
            except Exception as e:
                # print(f"Error checking {url}: {e}")
                continue
                
    except Exception as e:
        print(f"Selenium Driver Error: {e}")
    finally:
        if driver:
            driver.quit()
            
    return list(emails), list(phones)

