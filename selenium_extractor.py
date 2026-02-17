
"""
Selenium Email and Phone Number Extractor Module
"""

import re
import time
from threading import BoundedSemaphore
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from urllib.parse import urljoin
from selenium.common.exceptions import TimeoutException

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
PAGE_LOAD_TIMEOUT = 12
SCRIPT_TIMEOUT = 12
RENDER_WAIT_SECONDS = 1.2

def _get_selenium_driver():
    """Create and return a configured Chrome driver"""
    # Load environment variables
    from dotenv import load_dotenv
    import os
    load_dotenv()
    
    # Check for headless mode in env, default to True if not specified or invalid
    headless_env = os.getenv("HEADLESS", "True").lower()
    is_headless = headless_env in ("true", "1", "yes")

    chrome_options = Options()
    chrome_options.page_load_strategy = "eager"
    if is_headless:
        # Use new headless mode for better compatibility
        chrome_options.add_argument("--headless=new") 
    
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--disable-extensions")
    chrome_options.add_argument("--disable-infobars")
    chrome_options.add_argument("--start-maximized")
    chrome_options.add_argument("--blink-settings=imagesEnabled=false") # Disable images for speed
    
    # Suppress logging
    chrome_options.add_argument("--log-level=3")
    
    # 1. Try System Driver First (Preferred for Streamlit Cloud / CI/CD)
    # Streamlit Cloud installs chromium-driver which matches the installed chromium.
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
        driver.set_script_timeout(SCRIPT_TIMEOUT)
        return driver
    except Exception as e_system:
        # print(f"System driver not found or failed: {e_system}. Trying WebDriverManager...")
        
        # 2. Fallback to WebDriverManager (Preferred for Local Dev)
        try:
            from selenium.webdriver.chrome.service import Service
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            driver.set_script_timeout(SCRIPT_TIMEOUT)
            return driver
        except Exception as e_manager:
            print(f"Both system driver and WebDriverManager failed.")
            print(f"System Error: {e_system}")
            print(f"Manager Error: {e_manager}")
            raise e_manager

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
        
        # Keep fallback lightweight to avoid long-tail stalls.
        paths = ["", "/contact", "/about"]
        
        for path in paths:
            try:
                url = urljoin(website, path)
                try:
                    driver.get(url)
                except TimeoutException:
                    continue
                
                # Wait a bit for JS to execute
                time.sleep(RENDER_WAIT_SECONDS)
                
                page_source = driver.page_source
                
                # Extract emails
                found_emails = EMAIL_REGEX.findall(page_source)
                for email in found_emails:
                    if not email.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
                        if not any(x in email.lower() for x in ["example.com", "test@", "noreply@"]):
                            emails.add(email)

                # If homepage already has an email, skip scanning fallback pages.
                if path == "" and emails:
                    break
                
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

                if emails and phones:
                    break
                        
            except Exception as e:
                # print(f"Error checking {url}: {e}")
                continue
                
    except Exception as e:
        print(f"Selenium Driver Error: {e}")
    finally:
        if driver:
            driver.quit()
            
    return list(emails), list(phones)
