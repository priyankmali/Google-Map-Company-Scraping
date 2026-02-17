
"""
Test Email Extractor
Usage: python3 test_email_extractor.py <url>
"""
import json
import os
import subprocess
import sys
import time
import pandas as pd
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


def _extract_with_timeout(website, timeout_seconds=45):
    start_time = time.time()
    code = """
import json
import sys
from email_extractor import extract_emails_and_phones_from_site

emails, phones = extract_emails_and_phones_from_site(sys.argv[1])
print(json.dumps({"emails": emails, "phones": phones}))
""".strip()

    try:
        completed = subprocess.run(
            [sys.executable, "-c", code, website],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "emails": [],
            "phones": [],
            "duration": timeout_seconds,
            "error": f"Timed out after {timeout_seconds}s",
        }

    duration = time.time() - start_time
    if completed.returncode != 0:
        return {
            "status": "error",
            "emails": [],
            "phones": [],
            "duration": duration,
            "error": completed.stderr.strip() or f"Exit code {completed.returncode}",
        }

    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        return {
            "status": "error",
            "emails": [],
            "phones": [],
            "duration": duration,
            "error": "No JSON output returned by subprocess",
        }

    try:
        payload = json.loads(lines[-1])
    except json.JSONDecodeError:
        return {
            "status": "error",
            "emails": [],
            "phones": [],
            "duration": duration,
            "error": f"Invalid subprocess output: {lines[-1][:200]}",
        }

    return {
        "status": "success",
        "emails": payload.get("emails", []) or [],
        "phones": payload.get("phones", []) or [],
        "duration": duration,
    }


def test_excel_extraction(excel_path="we.xlsx", timeout_seconds=45, max_rows=None):
    """
    Run extractor for each website in an Excel file with per-site timeout.
    Helps detect rows where extraction hangs or becomes too slow.
    """
    if not os.path.exists(excel_path):
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    df = pd.read_excel(excel_path)
    if "website" not in df.columns:
        raise ValueError("Excel must contain a 'website' column")

    if max_rows is not None:
        df = df.head(max_rows)

    results = []
    total_start = time.time()

    for i, row in df.iterrows():
        website = row.get("website")
        name = row.get("name", f"row_{i}")

        if not isinstance(website, str) or not website.startswith("http"):
            results.append(
                {
                    "row": i,
                    "name": name,
                    "website": website,
                    "status": "invalid_website",
                    "duration_sec": 0,
                    "email_count": 0,
                    "phone_count": 0,
                    "emails": "",
                    "phones": "",
                    "error": "",
                }
            )
            continue

        print(f"[{i + 1}/{len(df)}] Testing: {website}")
        run = _extract_with_timeout(website, timeout_seconds=timeout_seconds)
        emails = run.get("emails", [])
        phones = run.get("phones", [])
        status = run.get("status", "error")
        duration = run.get("duration", 0)

        results.append(
            {
                "row": i,
                "name": name,
                "website": website,
                "status": status,
                "duration_sec": round(duration, 2),
                "email_count": len(emails),
                "phone_count": len(phones),
                "emails": ", ".join(emails),
                "phones": ", ".join(phones),
                "error": run.get("error", ""),
            }
        )

        print(
            f"  -> status={status}, emails={len(emails)}, phones={len(phones)}, time={duration:.2f}s"
        )

    total_duration = time.time() - total_start
    result_df = pd.DataFrame(results)
    output_path = "we_extraction_test_results.xlsx"
    result_df.to_excel(output_path, index=False)

    print("\n" + "=" * 60)
    print(f"Completed {len(result_df)} rows in {total_duration:.2f}s")
    print(f"Success: {(result_df['status'] == 'success').sum()}")
    print(f"Timeout: {(result_df['status'] == 'timeout').sum()}")
    print(f"Error: {(result_df['status'] == 'error').sum()}")
    print(f"Invalid website: {(result_df['status'] == 'invalid_website').sum()}")
    print(f"Saved results to: {output_path}")
    print("=" * 60)


if __name__ == "__main__":
    # Usage examples:
    # python3 test_email_extractor.py https://example.com
    # python3 test_email_extractor.py we.xlsx
    # python3 test_email_extractor.py we.xlsx 45 20
    if len(sys.argv) > 1 and sys.argv[1].lower().endswith(".xlsx"):
        excel_path = sys.argv[1]
        timeout_seconds = int(sys.argv[2]) if len(sys.argv) > 2 else 45
        max_rows = int(sys.argv[3]) if len(sys.argv) > 3 else None
        test_excel_extraction(excel_path, timeout_seconds=timeout_seconds, max_rows=max_rows)
    elif len(sys.argv) > 1:
        test_url(sys.argv[1])
    else:
        test_excel_extraction("we.xlsx")
