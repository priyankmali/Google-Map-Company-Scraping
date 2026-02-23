
"""
Selenium Email and Phone Number Extractor Module
"""

import re
import time
from threading import BoundedSemaphore
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from urllib.parse import urljoin
from selenium.common.exceptions import TimeoutException
from bs4 import BeautifulSoup

# Email and Phone regex (Copied from email_extractor.py to be standalone)
EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)
SERVICE_KEYWORDS = {
    "development", "design", "marketing", "seo", "consulting", "testing",
    "support", "maintenance", "integration", "software", "application",
    "mobile", "web", "cloud", "devops", "automation", "analytics",
    "branding", "ui", "ux", "erp", "crm", "api", "ai", "machine learning",
    "solution", "solutions", "product", "products",
}
NAV_STOPWORDS = {
    "home", "about", "about us", "contact", "contact us", "services",
    "service", "products", "product", "career", "industries", "company",
    "portfolio", "blog", "our work", "why us",
}
NOISY_PHRASES = {
    "we have the expertise",
    "you've got the questions",
    "we've got the ideal software",
    "turn your ideas",
}

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
RENDER_WAIT_SECONDS = 0.7

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
    chrome_options.binary_location = os.getenv("CHROME_BINARY", "/usr/bin/chromium")
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
    
    # Try system drivers first to avoid stale cached chromedriver mismatches.
    candidate_drivers = [
        os.getenv("CHROMEDRIVER_PATH"),
        "/usr/bin/chromedriver",
        "/usr/lib/chromium/chromedriver",
        "chromedriver",
    ]
    candidate_drivers = [p for p in candidate_drivers if p]

    last_error = None
    for driver_path in candidate_drivers:
        try:
            service = Service(executable_path=driver_path)
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            driver.set_script_timeout(SCRIPT_TIMEOUT)
            return driver
        except Exception as exc:
            last_error = exc

    # Optional local fallback only when explicitly enabled.
    if os.getenv("ALLOW_WDM_FALLBACK", "0").lower() in {"1", "true", "yes"}:
        try:
            from webdriver_manager.chrome import ChromeDriverManager
            os.environ.setdefault("WDM_DISABLE_STATS", "1")
            service = Service(ChromeDriverManager().install())
            driver = webdriver.Chrome(service=service, options=chrome_options)
            driver.set_page_load_timeout(PAGE_LOAD_TIMEOUT)
            driver.set_script_timeout(SCRIPT_TIMEOUT)
            return driver
        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise RuntimeError("No usable ChromeDriver found.")

def extract_emails_and_phones_with_selenium(website):
    """
    Extract emails and phone numbers from a website using Selenium
    Wrapper that ensures we don't exceed max concurrent browsers
    """
    with SELENIUM_SEMAPHORE:
        return _extract_logic(website, emails_only=False)


def extract_emails_with_selenium(website):
    """
    Extract only emails from a website using Selenium.
    Wrapper that ensures we don't exceed max concurrent browsers.
    """
    with SELENIUM_SEMAPHORE:
        return _extract_logic(website, emails_only=True)


def extract_emails_and_services_with_selenium(website):
    """Extract emails and service names from a website using Selenium."""
    with SELENIUM_SEMAPHORE:
        return _extract_logic(website, emails_only=True, services_only=True)


def _normalize_service_name(text):
    cleaned = re.sub(r"\s+", " ", (text or "").strip())
    cleaned = re.sub(r"^[>\-•·\u2022]+\s*", "", cleaned)
    return cleaned


def _looks_like_service_name(text):
    lowered = text.lower()
    if len(text) < 4 or len(text) > 80:
        return False
    if any(ch in lowered for ch in ["@", "http://", "https://"]):
        return False
    if re.search(r"\d{4,}", lowered):
        return False
    if lowered in NAV_STOPWORDS:
        return False
    if len(lowered.split()) == 1 and lowered in {"software", "service", "solution", "product"}:
        return False
    return any(k in lowered for k in SERVICE_KEYWORDS)


def _is_compact_service_label(text):
    lowered = text.lower()
    if len(text.split()) > 6:
        return False
    if any(p in lowered for p in NOISY_PHRASES):
        return False
    if any(ch in text for ch in [".", "?", "!", ":", ";"]):
        return False
    return True


def _extract_navbar_services_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    services = set()
    nav_scopes = soup.select("nav, header, .navbar, .main-menu, .menu, .navigation")

    for scope in nav_scopes:
        trigger_found = False
        triggers = scope.find_all(["a", "button", "span"], string=True)
        for trigger in triggers:
            t = _normalize_service_name(trigger.get_text(" ", strip=True)).lower()
            if "service" in t:
                trigger_found = True
                break
        if not trigger_found:
            continue

        for item in scope.select("li a, li span, .dropdown-menu a, .sub-menu a, .mega-menu a"):
            text = _normalize_service_name(item.get_text(" ", strip=True))
            if _looks_like_service_name(text) and _is_compact_service_label(text):
                services.add(text)

    return services


def _extract_footer_services_from_html(html):
    soup = BeautifulSoup(html, "html.parser")
    services = set()
    footer_scopes = soup.select("footer, .footer, #footer")

    for scope in footer_scopes:
        candidate_blocks = []
        for tag in scope.find_all(["h2", "h3", "h4", "h5", "strong", "b"]):
            title = _normalize_service_name(tag.get_text(" ", strip=True)).lower()
            if "service" in title:
                block = tag.find_parent(["div", "section", "article", "ul"]) or scope
                candidate_blocks.append(block)

        if not candidate_blocks:
            candidate_blocks = [scope]

        for block in candidate_blocks:
            for item in block.select("li, a, p, span"):
                text = _normalize_service_name(item.get_text(" ", strip=True))
                if _looks_like_service_name(text) and _is_compact_service_label(text):
                    services.add(text)

    return services


def _extract_services_from_open_menu(driver):
    services = set()
    xpaths = [
        "//*[contains(@class,'dropdown') or contains(@class,'menu') or contains(@class,'mega') or contains(@class,'sub')]//*[self::a or self::li or self::span]",
        "//*[contains(@id,'menu') or contains(@id,'service')]//*[self::a or self::li or self::span]",
    ]
    for xp in xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)
        except Exception:
            elems = []
        for elem in elems:
            try:
                if not elem.is_displayed():
                    continue
                text = _normalize_service_name(elem.text)
                if _looks_like_service_name(text) and _is_compact_service_label(text):
                    services.add(text)
            except Exception:
                continue
    return services


def _extract_services_from_visible_dom(driver):
    services = set()
    xpaths = [
        "//*[self::a or self::li or self::span or self::div or self::p][normalize-space(text())!='']",
    ]
    for xp in xpaths:
        try:
            elems = driver.find_elements(By.XPATH, xp)
        except Exception:
            elems = []
        for elem in elems:
            try:
                if not elem.is_displayed():
                    continue
                txt = _normalize_service_name(elem.text)
                if _looks_like_service_name(txt) and _is_compact_service_label(txt):
                    services.add(txt)
            except Exception:
                continue
    return services


def _extract_services_from_service_page_html(html):
    soup = BeautifulSoup(html, "html.parser")
    services = set()
    for item in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = _normalize_service_name(item.get_text(" ", strip=True))
        lowered = text.lower()
        if not text:
            continue
        if lowered in NAV_STOPWORDS:
            continue
        if lowered in {"services", "our services", "service", "products", "our products", "product", "solutions", "our solutions", "solution"}:
            continue
        services.add(text)
    return services


def _extract_emails_from_html(html):
    emails = set()
    found_emails = EMAIL_REGEX.findall(html)
    for email in found_emails:
        if not email.lower().endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
            if not any(x in email.lower() for x in ["example.com", "test@", "noreply@"]):
                emails.add(email)
    return emails


def _try_open_services_dropdown(driver):
    discovered = set()
    try:
        triggers = driver.find_elements(
            By.XPATH,
            "//*[self::a or self::button or self::span][contains(translate(normalize-space(.), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'service')]"
        )
    except Exception:
        return discovered

    for elem in triggers[:6]:
        try:
            if not elem.is_displayed():
                continue
            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", elem)
            ActionChains(driver).move_to_element(elem).pause(0.4).perform()
            time.sleep(0.8)
            discovered.update(_extract_services_from_open_menu(driver))
            discovered.update(_extract_navbar_services_from_html(driver.page_source))
            discovered.update(_extract_services_from_visible_dom(driver))
            if discovered:
                return discovered
            elem.click()
            time.sleep(0.9)
            discovered.update(_extract_services_from_open_menu(driver))
            discovered.update(_extract_navbar_services_from_html(driver.page_source))
            discovered.update(_extract_services_from_visible_dom(driver))
            if discovered:
                return discovered
        except Exception:
            continue
    return discovered


def _extract_logic(website, emails_only=False, services_only=False):
    emails = set()
    phones = set()
    services = set()
    driver = None
    
    try:
        driver = _get_selenium_driver()
        
        # 1) Homepage first: emails + navbar dropdown services.
        try:
            driver.get(urljoin(website, ""))
            time.sleep(RENDER_WAIT_SECONDS)
            discovered = _try_open_services_dropdown(driver)
            home_source = driver.page_source
            emails.update(_extract_emails_from_html(home_source))
            if services_only:
                services.update(discovered)
                services.update(_extract_navbar_services_from_html(home_source))
                services.update(_extract_footer_services_from_html(home_source))
                services.update(_extract_services_from_open_menu(driver))
                services.update(_extract_services_from_visible_dom(driver))
        except TimeoutException:
            pass
        except Exception:
            pass

        # 2) Fetch basic pages for emails.
        paths = ["/contact", "/about", "/contact-us"]
        for path in paths:
            try:
                driver.get(urljoin(website, path))
                time.sleep(RENDER_WAIT_SECONDS)
                page_source = driver.page_source
                emails.update(_extract_emails_from_html(page_source))

                if not emails_only:
                    potential_phones = re.findall(r'(?:\+?\d{1,3}[-\s.]?)?(?:\(?\d{3}\)?[-\s.]?)?\d{3}[-\s.]?\d{4,6}', page_source)
                    for phone in potential_phones:
                        phone_clean = phone.strip()
                        if any(x in phone_clean for x in [",", ";", "<", ">", "{", "}"]):
                            continue
                        parts = re.split(r'[-\s.]', phone_clean)
                        parts = [p for p in parts if p.isdigit()]
                        if len(parts) == 3 and all(len(p) <= 3 for p in parts): continue
                        if phone_clean.startswith("0") and len(phone_clean) < 10: continue
                        if phone_clean.replace(" ", "").isdigit() and len(phone_clean.replace(" ", "")) < 10: continue
                        if "." in phone_clean and phone_clean.replace(".", "").isdigit():
                             if len(phone_clean.split(".")[1]) > 0: continue
                        digits_only = re.sub(r"\D", "", phone_clean)
                        if 10 <= len(digits_only) <= 15 and len(set(digits_only)) >= 3:
                            phones.add(phone_clean)
            except TimeoutException:
                continue
            except Exception:
                continue

        # 3) If no services from navbar, open service/product pages and extract service list text.
        if services_only and not services:
            for path in ["/services", "/service", "/our-services", "/our-service", "/products", "/product", "/solutions"]:
                try:
                    driver.get(urljoin(website, path))
                    time.sleep(RENDER_WAIT_SECONDS)
                    page_source = driver.page_source
                    services.update(_extract_services_from_service_page_html(page_source))
                    emails.update(_extract_emails_from_html(page_source))
                except TimeoutException:
                    continue
                except Exception:
                    continue
                
    except Exception as e:
        print(f"Selenium Driver Error: {e}")
    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass
            
    if emails_only and services_only:
        return list(emails), list(services)
    if emails_only:
        return list(emails)
    return list(emails), list(phones)
