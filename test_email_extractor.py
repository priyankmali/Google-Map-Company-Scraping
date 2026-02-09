
"""
Test Email Extractor
Usage: python3 test_email_extractor.py <url>
"""
import sys
import time
from email_extractor import extract_emails_and_phones_from_site

def test_url(url):
    print(f"Testing URL: {url}")
    print("-" * 50)
    
    start_time = time.time()
    emails, phones = extract_emails_and_phones_from_site(url)
    duration = time.time() - start_time
    
    print(f"Time Taken: {duration:.2f} seconds")
    print(f"Emails Found: {len(emails)}")
    for email in emails:
        print(f"  - {email}")
        
    print(f"Phones Found: {len(phones)}")
    for phone in phones:
        print(f"  - {phone}")
    print("-" * 50)

if __name__ == "__main__":
    test_urls = []
    if len(sys.argv) > 1:
        test_urls.append(sys.argv[1])
    else:
        # Default test cases
        print("No URL provided. Running default tests...")
        test_urls = [
            "https://docpaysolution.com", # Needs Selenium
            # "https://www.gujjuinfotech.com/"
        ]

    for url in test_urls:
        test_url(url)
