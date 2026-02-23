"""
Google Maps Details Extractor Module

This module handles the extraction of company details from Google Maps.
"""

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from concurrent.futures import ThreadPoolExecutor, as_completed
import time


from selenium.webdriver.chrome.service import Service
import os

# ============= CREATE DRIVER ================
def create_driver(headless=True):
    """Create and configure Chrome WebDriver"""
    options = webdriver.ChromeOptions()
    
    # Load environment variables
    from dotenv import load_dotenv
    load_dotenv()
    
    # Check for headless mode in env
    # If env var exists, it OVERRIDES the function argument
    if os.getenv("HEADLESS"):
         headless_env = os.getenv("HEADLESS", "True").lower()
         headless = headless_env in ("true", "1", "yes")

    # Standard headless options
    if headless:
        options.add_argument("--headless=new")
    options.binary_location = os.getenv("CHROME_BINARY", "/usr/bin/chromium")
    
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--start-maximized")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option('useAutomationExtension', False)

    # Prefer system drivers first to avoid stale cached chromedriver mismatches.
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
            return webdriver.Chrome(service=service, options=options)
        except Exception as exc:
            last_error = exc

    # Optional local fallback only when explicitly enabled.
    if os.getenv("ALLOW_WDM_FALLBACK", "0").lower() in {"1", "true", "yes"}:
        try:
            os.environ.setdefault("WDM_DISABLE_STATS", "1")
            from webdriver_manager.chrome import ChromeDriverManager
            service = Service(ChromeDriverManager().install())
            return webdriver.Chrome(service=service, options=options)
        except Exception as exc:
            last_error = exc

    if last_error:
        raise last_error
    raise RuntimeError("No usable ChromeDriver found.")


def wait_for_results(driver, timeout=25):
    """Wait for Google Maps search results to load"""
    WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located(
            (By.XPATH, '//a[contains(@href,"/place/")]')
        )
    )


def scroll_until_end(driver, pause=2, max_idle=5, max_scrolls=50):
    """Scroll through Google Maps results panel to collect all place URLs"""
    panel = driver.find_element(
        By.XPATH, '//div[contains(@aria-label,"Results")]'
    )

    links = set()
    idle_rounds = 0
    scroll_count = 0
    
    # IMPORTANT: Collect initial visible links BEFORE scrolling
    time.sleep(2)
    initial_items = driver.find_elements(
        By.XPATH, '//a[contains(@href,"/place/")]'
    )
    for item in initial_items:
        href = item.get_attribute("href")
        if href:
            links.add(href)

    while True:
        scroll_count += 1

        # Scroll panel
        driver.execute_script(
            "arguments[0].scrollTop = arguments[0].scrollHeight",
            panel
        )
        time.sleep(pause)

        # Collect URLs
        items = driver.find_elements(
            By.XPATH, '//a[contains(@href,"/place/")]'
        )

        before = len(links)
        for item in items:
            href = item.get_attribute("href")
            if href:
                links.add(href)

        after = len(links)

        # Check growth
        if after == before:
            idle_rounds += 1
        else:
            idle_rounds = 0

        # Condition 1: End-of-list detected
        end_elements = driver.find_elements(
            By.XPATH,
            '//*[contains(text(),"You\'ve reached the end of the list")]'
        )
        if end_elements:
            break

        # Condition 2: No new data after multiple scrolls
        if idle_rounds >= max_idle:
            break

        # Condition 3: Hard safety limit
        if scroll_count >= max_scrolls:
            break

    return list(links)


def extract_place_details(place_url, retry_count=0, max_retries=1):
    """Extract details (name, address, phone, website) from a Google Maps place URL"""
    driver = None
    should_retry = False

    data = {
        "place_url": place_url,
        "name": None,
        "address": None,
        "phone": None,
        "website": None,
        "status": "success",
        "error": None
    }

    try:
        driver = create_driver(headless=True)
        driver.get(place_url)
        
        # Smart wait for page load
        wait = WebDriverWait(driver, 20)
        
        # Wait until name is visible (page fully loaded)
        wait.until(EC.presence_of_element_located((By.XPATH, "//h1")))
        
        # Single scroll to trigger lazy loading (optimized)
        driver.execute_script("window.scrollTo(0, 500);")
        time.sleep(1)

        # Extract name
        try:
            name_element = driver.find_element(By.XPATH, "//h1")
            data["name"] = name_element.text
        except Exception as e:
            data["error"] = f"Name not found: {str(e)}"

        # Extract address with smart wait
        try:
            address_wait = WebDriverWait(driver, 5)
            address_element = address_wait.until(
                EC.presence_of_element_located((
                    By.XPATH,
                    '//button[@data-item-id="address"]//div[contains(@class,"fontBodyMedium")]'
                ))
            )
            data["address"] = address_element.text
        except:
            pass

        # Extract phone with smart wait
        try:
            phone_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    '//button[contains(@data-item-id,"phone")]//div[contains(@class,"fontBodyMedium")]'
                ))
            )
            data["phone"] = phone_element.text
        except:
            pass

        # Extract website with smart wait
        try:
            website_element = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((
                    By.XPATH,
                    '//a[@data-item-id="authority"]'
                ))
            )
            data["website"] = website_element.get_attribute("href")
        except:
            pass
        
        # Retry if no name found (indicates page didn't load)
        if data["name"] is None and retry_count < max_retries:
            should_retry = True

    except Exception as e:
        data["status"] = "failed"
        data["error"] = str(e)
        
        # Retry on failure
        if retry_count < max_retries:
            should_retry = True

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass

    if should_retry:
        time.sleep(2)
        return extract_place_details(place_url, retry_count + 1, max_retries)

    return data


def scrape_single_location(args):
    """Scrape Google Maps for a single keyword-location combination"""
    keyword, location = args

    driver = None

    try:
        # MUST be headless for Streamlit Cloud / Server environments
        driver = create_driver(headless=True)
        driver.get("https://www.google.com/maps")
        time.sleep(4)

        query = f"{keyword} in {location}"

        search_box = driver.find_element(By.NAME, "q")
        search_box.clear()
        search_box.send_keys(query + Keys.ENTER)

        wait_for_results(driver)

        places = scroll_until_end(driver)

        return [
            {
                "place_url": url,
                "search_location": location
            }
            for url in places
        ]

    finally:
        if driver:
            try:
                driver.quit()
            except Exception:
                pass


def run_detail_extraction(df_places, progress_callback=None, status_callback=None):
    """
    Extract details for all places in the dataframe
    
    Args:
        df_places: DataFrame with 'place_url' column
        progress_callback: Function to call with progress (0.0 to 1.0)
        status_callback: Function to call with status text
    
    Returns:
        DataFrame with extracted details
    """
    import pandas as pd
    
    total_places = len(df_places)
    results = []
    workers = 4  # Optimized parallel processing

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(extract_place_details, row["place_url"]): idx
            for idx, row in df_places.iterrows()
        }

        completed = 0
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            
            completed += 1
            
            # Update progress
            if progress_callback:
                progress_callback(completed / total_places)
            
            # Update status
            if status_callback:
                company_name = result.get("name") or "Unknown"
                status_msg = f"✅ {completed}/{total_places}: {company_name}"
                if result.get("status") == "failed":
                    status_msg = f"⚠️ {completed}/{total_places}: {company_name} (failed)"
                status_callback(status_msg)
            
            # Minimal delay between requests
            time.sleep(0.5)

    return pd.DataFrame(results)
