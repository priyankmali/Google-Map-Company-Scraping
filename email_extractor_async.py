"""
Async Email and Phone Number Extractor Module

This module is experimental and runs HTTP scraping with asyncio + aiohttp.
Selenium fallback remains blocking and is executed in a worker thread.
"""

import asyncio
import re
from urllib.parse import urljoin

import aiohttp


EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
)

PHONE_FINDALL_REGEX = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[-\s.]?)?(?:\(?\d{2,4}\)?[-\s.]?)?\d{3,4}[-\s.]?\d{3,4}(?:[-\s.]?\d{2,4})?(?!\d)"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

DEFAULT_PATHS = [
    "",
    "/contact",
    "/contact-us",
    "/contactus",
    "/about",
    "/about-us",
    "/get-in-touch",
    "/reach-us",
    "/team",
    "/Contact-us",
    "/enquiry",
]
MAX_HTML_BYTES = 1_000_000


class HomePageTimeoutError(Exception):
    """Raised when homepage fetch exceeds the allowed timeout."""


def _is_valid_email(email):
    lowered = email.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
        return False
    if any(x in lowered for x in ["example.com", "test@", "noreply@"]):
        return False
    return True


def _normalize_mobile_number(phone):
    """
    Normalize to 10-digit Indian mobile number.
    Accepts variants like +91XXXXXXXXXX, 91XXXXXXXXXX, 0XXXXXXXXXX, XXXXXXXXXX.
    """
    digits_only = re.sub(r"\D", "", phone.strip())
    if not digits_only:
        return None

    if len(digits_only) == 12 and digits_only.startswith("91"):
        digits_only = digits_only[2:]
    elif len(digits_only) == 11 and digits_only.startswith("0"):
        digits_only = digits_only[1:]

    if len(digits_only) != 10:
        return None
    if digits_only[0] not in "6789":
        return None
    if len(set(digits_only)) < 3:
        return None
    if digits_only in {"1234567890", "9876543210"}:
        return None

    return digits_only


def _is_valid_phone(phone):
    phone_clean = phone.strip()
    if any(x in phone_clean for x in [",", ";", "<", ">", "{", "}"]):
        return False

    parts = re.split(r"[-\s.]", phone_clean)
    parts = [p for p in parts if p.isdigit()]
    if len(parts) == 3 and all(len(p) <= 3 for p in parts):
        return False

    if phone_clean.startswith("0") and len(phone_clean) < 10:
        return False

    digits_no_space = phone_clean.replace(" ", "")
    if digits_no_space.isdigit() and len(digits_no_space) < 10:
        return False

    if "." in phone_clean and phone_clean.replace(".", "").isdigit():
        if len(phone_clean.split(".")[1]) > 0:
            return False

    if _normalize_mobile_number(phone_clean) is None:
        return False

    return True


def _extract_contacts_from_text(text):
    emails = {
        email for email in EMAIL_REGEX.findall(text)
        if _is_valid_email(email)
    }
    phones = {
        _normalize_mobile_number(phone)
        for phone in PHONE_FINDALL_REGEX.findall(text)
        if _is_valid_phone(phone)
    }
    phones.discard(None)
    return emails, phones


async def _fetch_html(session, url, *, raise_on_timeout=False):
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status != 200:
                return None
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                return None

            chunks = []
            size = 0
            async for chunk in response.content.iter_chunked(16 * 1024):
                size += len(chunk)
                if size > MAX_HTML_BYTES:
                    break
                chunks.append(chunk)

            if not chunks:
                return None

            raw = b"".join(chunks)
            return raw.decode("utf-8", errors="ignore")
    except asyncio.TimeoutError:
        if raise_on_timeout:
            raise
        return None
    except Exception:
        return None


async def extract_emails_and_phones_from_site_async(
    website,
    session,
    *,
    paths=None,
    selenium_semaphore=None,
    selenium_timeout=12,
    selenium_fallback=True,
    fallback_if_phones_found=False,
    homepage_timeout=20,
    return_meta=False
):
    """
    Extract emails and phones for one website using async HTTP requests.
    """
    emails = set()
    phones = set()
    candidate_paths = paths or DEFAULT_PATHS
    selenium_fallback_used = False

    homepage_url = urljoin(website, "")
    try:
        homepage = await asyncio.wait_for(
            _fetch_html(session, homepage_url, raise_on_timeout=True),
            timeout=homepage_timeout
        )
    except asyncio.TimeoutError as e:
        raise HomePageTimeoutError(
            f"Homepage timed out after {homepage_timeout}s: {homepage_url}"
        ) from e

    pages = [homepage]
    remaining_urls = [urljoin(website, path) for path in candidate_paths if path != ""]
    if remaining_urls:
        tasks = [_fetch_html(session, url) for url in remaining_urls]
        extra_pages = await asyncio.gather(*tasks, return_exceptions=False)
        pages.extend(extra_pages)

    for page in pages:
        if not page:
            continue
        found_emails, found_phones = _extract_contacts_from_text(page)
        emails.update(found_emails)
        phones.update(found_phones)

    should_fallback = not emails and (fallback_if_phones_found or not phones)
    if selenium_fallback and should_fallback:
        try:
            from selenium_extractor import extract_emails_and_phones_with_selenium
            if selenium_semaphore is None:
                selenium_semaphore = asyncio.Semaphore(2)

            async with selenium_semaphore:
                sel_emails, sel_phones = await asyncio.wait_for(
                    asyncio.to_thread(
                        extract_emails_and_phones_with_selenium,
                        website
                    ),
                    timeout=selenium_timeout
                )
            selenium_fallback_used = True
            emails.update(sel_emails)
            normalized_sel_phones = {
                _normalize_mobile_number(phone)
                for phone in sel_phones
                if _is_valid_phone(phone)
            }
            normalized_sel_phones.discard(None)
            phones.update(normalized_sel_phones)
        except Exception:
            pass

    if return_meta:
        return list(emails), list(phones), {"selenium_fallback_used": selenium_fallback_used}

    return list(emails), list(phones)


async def _email_phone_worker_async(
    row,
    session,
    site_semaphore,
    selenium_semaphore,
    per_site_timeout=45,
    selenium_timeout=12,
    selenium_fallback=True,
    fallback_if_phones_found=False,
    homepage_timeout=20
):
    result = {
        "name": row.get("name"),
        "address": row.get("address"),
        "phone": row.get("phone"),
        "website": row.get("website"),
        "emails": None,
        "status": "success",
        "duration_sec": 0.0,
        "selenium_fallback_used": False
    }
    started = asyncio.get_running_loop().time()

    website = row.get("website")
    if not isinstance(website, str) or not website.startswith("http"):
        result["status"] = "no_website"
        result["duration_sec"] = round(asyncio.get_running_loop().time() - started, 2)
        return result

    try:
        async with site_semaphore:
            emails, scraped_phones, meta = await asyncio.wait_for(
                extract_emails_and_phones_from_site_async(
                    website,
                    session,
                    selenium_semaphore=selenium_semaphore,
                    selenium_timeout=selenium_timeout,
                    selenium_fallback=selenium_fallback,
                    fallback_if_phones_found=fallback_if_phones_found,
                    homepage_timeout=homepage_timeout,
                    return_meta=True
                ),
                timeout=per_site_timeout
            )
            result["selenium_fallback_used"] = bool(meta.get("selenium_fallback_used"))
    except HomePageTimeoutError:
        result["status"] = "home_timeout"
        result["duration_sec"] = round(asyncio.get_running_loop().time() - started, 2)
        return result
    except asyncio.TimeoutError:
        result["status"] = "timeout"
        result["duration_sec"] = round(asyncio.get_running_loop().time() - started, 2)
        return result

    if emails:
        result["emails"] = ", ".join(sorted(emails))

    all_phones = set()
    gmaps_phone = row.get("phone")
    if gmaps_phone and isinstance(gmaps_phone, str):
        all_phones.add(gmaps_phone.strip())
    for phone in scraped_phones:
        if phone and isinstance(phone, str):
            all_phones.add(phone.strip())

    if all_phones:
        result["phone"] = ", ".join(sorted(all_phones))

    if not emails and not all_phones:
        result["status"] = "no_contact_info"
    elif not emails:
        result["status"] = "no_emails"

    result["duration_sec"] = round(asyncio.get_running_loop().time() - started, 2)
    return result


async def _run_email_extraction_async(
    df_input,
    progress_callback=None,
    status_callback=None,
    *,
    max_concurrent_sites=20,
    max_connections=100,
    request_timeout=12,
    per_site_timeout=45,
    max_concurrent_selenium_fallbacks=2,
    selenium_timeout=12,
    selenium_fallback=True,
    fallback_if_phones_found=False,
    homepage_timeout=20
):
    import pandas as pd

    total = len(df_input)
    if total == 0:
        return pd.DataFrame([])

    timeout = aiohttp.ClientTimeout(total=request_timeout)
    connector = aiohttp.TCPConnector(limit=max_connections, ssl=False)
    site_semaphore = asyncio.Semaphore(max_concurrent_sites)
    selenium_semaphore = asyncio.Semaphore(max_concurrent_selenium_fallbacks)
    results = []

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=HEADERS,
        connector=connector
    ) as session:
        tasks = [
            asyncio.create_task(
                _email_phone_worker_async(
                    row,
                    session,
                    site_semaphore,
                    selenium_semaphore,
                    per_site_timeout=per_site_timeout,
                    selenium_timeout=selenium_timeout,
                    selenium_fallback=selenium_fallback,
                    fallback_if_phones_found=fallback_if_phones_found,
                    homepage_timeout=homepage_timeout
                )
            )
            for _, row in df_input.iterrows()
        ]

        completed = 0
        for task in asyncio.as_completed(tasks):
            result = await task
            results.append(result)
            completed += 1

            if progress_callback:
                progress_callback(completed / total)

            if status_callback:
                name = result.get("name") or "Unknown Company"
                emails = result.get("emails")
                phones = result.get("phone")
                status = result.get("status")
                duration = result.get("duration_sec")
                used_selenium = result.get("selenium_fallback_used")
                suffix = f" ({duration}s)"
                if used_selenium:
                    suffix = f"{suffix} [selenium]"
                if status == "home_timeout":
                    status_callback(f"⏭️ {name} → Homepage > {homepage_timeout}s, skipped{suffix}")
                elif status == "timeout":
                    status_callback(f"⏱️ {name} → Timed out, skipped{suffix}")
                elif emails and phones:
                    status_callback(f"✅ {name} → Emails: {emails} | Phones: {phones}{suffix}")
                elif emails:
                    status_callback(f"✅ {name} → Emails: {emails}{suffix}")
                elif phones:
                    status_callback(f"✅ {name} → Phones: {phones}{suffix}")
                else:
                    status_callback(f"⚠️ {name} → No contact info found{suffix}")

    return pd.DataFrame(results)


def run_email_extraction_async(
    df_input,
    progress_callback=None,
    status_callback=None,
    *,
    max_concurrent_sites=20,
    max_connections=100,
    request_timeout=12,
    per_site_timeout=45,
    max_concurrent_selenium_fallbacks=2,
    selenium_timeout=12,
    selenium_fallback=True,
    fallback_if_phones_found=False,
    homepage_timeout=20
):
    """
    Sync wrapper for Streamlit and scripts.
    """
    coro = _run_email_extraction_async(
        df_input,
        progress_callback=progress_callback,
        status_callback=status_callback,
        max_concurrent_sites=max_concurrent_sites,
        max_connections=max_connections,
        request_timeout=request_timeout,
        per_site_timeout=per_site_timeout,
        max_concurrent_selenium_fallbacks=max_concurrent_selenium_fallbacks,
        selenium_timeout=selenium_timeout,
        selenium_fallback=selenium_fallback,
        fallback_if_phones_found=fallback_if_phones_found,
        homepage_timeout=homepage_timeout
    )
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
