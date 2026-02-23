"""
Chunked async email extractor using aiohttp + BeautifulSoup.

This module extracts only emails (no mobile/phone extraction).
"""

import asyncio
import math
import re
from urllib.parse import urljoin, urlparse, urlunparse

import aiohttp
from bs4 import BeautifulSoup


EMAIL_REGEX = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_FINDALL_REGEX = re.compile(
    r"(?<!\d)(?:\+?\d{1,3}[-\s.]?)?(?:\(?\d{2,4}\)?[-\s.]?)?\d{3,4}[-\s.]?\d{3,4}(?:[-\s.]?\d{2,4})?(?!\d)"
)
DEFAULT_PATHS = ["", "/contact", "/about", "/contact-us"]
SERVICE_PATHS = [
    "/services", "/service", "/our-services", "/our-service",
    "/products", "/product", "/solutions", "/what-we-do",
]
MAX_HTML_BYTES = 450_000
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
GENERIC_SERVICE_HEADINGS = {
    "services", "our services", "service",
    "products", "our products", "product",
    "solutions", "our solutions", "solution",
    "other supports", "support",
}
GENERIC_NAV_SERVICE_ITEMS = {
    "our products", "products", "product",
    "our services", "services", "service",
    "solutions", "our solutions", "solution",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


def _is_valid_email(email):
    lowered = email.lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp")):
        return False
    if any(x in lowered for x in ["example.com", "test@", "noreply@"]):
        return False
    return True


def _extract_emails_with_bs4(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    emails = {e for e in EMAIL_REGEX.findall(text) if _is_valid_email(e)}

    for a_tag in soup.find_all("a", href=True):
        href = (a_tag.get("href") or "").strip()
        if href.lower().startswith("mailto:"):
            mail = href.split(":", 1)[1].split("?", 1)[0].strip()
            if mail and _is_valid_email(mail):
                emails.add(mail)

    return emails


def _is_blank_value(value):
    if value is None:
        return True
    if isinstance(value, float) and math.isnan(value):
        return True
    text = str(value).strip().lower()
    return text in {"", "none", "null", "nan", "na", "-"}


def _normalize_mobile_number(phone):
    digits_only = re.sub(r"\D", "", (phone or "").strip())
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
    phone_clean = (phone or "").strip()
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
    return _normalize_mobile_number(phone_clean) is not None


def _extract_phones_with_bs4(html):
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text(" ", strip=True)
    phones = {
        _normalize_mobile_number(phone)
        for phone in PHONE_FINDALL_REGEX.findall(text)
        if _is_valid_phone(phone)
    }
    phones.discard(None)
    return phones


def _website_variants(website):
    """
    Return normalized website candidates.
    Prefer https, then fallback to original/http when needed.
    """
    raw = (website or "").strip()
    if not raw:
        return []

    parsed = urlparse(raw)
    if not parsed.scheme:
        parsed = urlparse("https://" + raw)

    cleaned = parsed._replace(query="", fragment="")
    primary = urlunparse(cleaned)
    variants = [primary]

    if cleaned.scheme == "http":
        variants.insert(0, urlunparse(cleaned._replace(scheme="https")))
    elif cleaned.scheme == "https":
        variants.append(urlunparse(cleaned._replace(scheme="http")))

    seen = set()
    ordered = []
    for v in variants:
        v = v.rstrip("/")
        if v not in seen:
            seen.add(v)
            ordered.append(v)
    return ordered


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


def _extract_navbar_services_bs4(html):
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


def _extract_footer_services_bs4(html):
    soup = BeautifulSoup(html, "html.parser")
    services = set()

    footer_scopes = soup.select("footer, .footer, #footer")
    for scope in footer_scopes:
        # Find footer blocks that look like service columns.
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


def _is_weak_service_set(services):
    if not services:
        return True
    lowered = {s.strip().lower() for s in services if s and str(s).strip()}
    if not lowered:
        return True
    # If all extracted values are generic labels, force fallback to service pages.
    return all(item in GENERIC_NAV_SERVICE_ITEMS for item in lowered)


def _extract_services_from_page_bs4(html):
    soup = BeautifulSoup(html, "html.parser")
    services = set()
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6"]):
        text = _normalize_service_name(heading.get_text(" ", strip=True))
        lowered = text.lower()
        if not text:
            continue
        # Keep fallback strict: only meaningful H1 from service/product pages.
        if lowered in GENERIC_SERVICE_HEADINGS:
            continue
        if lowered in NAV_STOPWORDS:
            continue
        services.add(text)

    return services


async def _fetch_html(session, url):
    try:
        async with session.get(url, allow_redirects=True) as response:
            if response.status >= 400:
                return None, response.status, str(response.url)
            content_type = (response.headers.get("Content-Type") or "").lower()
            if "text/html" not in content_type and "application/xhtml+xml" not in content_type:
                return None, response.status, str(response.url)

            chunks = []
            size = 0
            async for chunk in response.content.iter_chunked(16 * 1024):
                size += len(chunk)
                if size > MAX_HTML_BYTES:
                    break
                chunks.append(chunk)

            if not chunks:
                return None, response.status, str(response.url)

            raw = b"".join(chunks)
            return raw.decode("utf-8", errors="ignore"), response.status, str(response.url)
    except Exception:
        return None, None, None


async def _extract_emails_one_site(
    row,
    session,
    semaphore,
    email_paths,
    service_paths,
    *,
    selenium_fallback=False,
    bs4_enabled=True,
    stop_on_first_email=False,
):
    started = asyncio.get_running_loop().time()
    result = {
        "name": row.get("name"),
        "address": row.get("address"),
        "phone": row.get("phone") if not _is_blank_value(row.get("phone")) else row.get("contact"),
        "website": row.get("website"),
        "emails": None,
        "email_count": 0,
        "services": None,
        "service_count": 0,
        "services_source": None,
        "status": "success",
        "duration_sec": 0.0,
        "error": None,
        "selenium_fallback_used": False,
        "_row_idx": row.get("_row_idx"),
    }

    website = row.get("website")
    if not isinstance(website, str) or not website.startswith("http"):
        result["status"] = "invalid_website"
        result["duration_sec"] = round(asyncio.get_running_loop().time() - started, 2)
        return result
    website_candidates = _website_variants(website)
    if not website_candidates:
        result["status"] = "invalid_website"
        result["duration_sec"] = round(asyncio.get_running_loop().time() - started, 2)
        return result

    found_emails = set()
    found_services = set()
    service_sources = set()
    found_phones = set()
    navbar_services_found = False
    last_http_status = None
    last_final_url = None
    should_extract_contact = _is_blank_value(row.get("contact")) and _is_blank_value(row.get("phone"))

    try:
        if bs4_enabled:
            async with semaphore:
                for base_site in website_candidates:
                    # Step 1: homepage for emails + navbar services.
                    home_html, home_status, home_final = await _fetch_html(session, urljoin(base_site + "/", ""))
                    if home_status is not None:
                        last_http_status = home_status
                    if home_final:
                        last_final_url = home_final
                    if home_html:
                        found_emails.update(_extract_emails_with_bs4(home_html))
                        nav_services = _extract_navbar_services_bs4(home_html)
                        if nav_services:
                            found_services.update(nav_services)
                            service_sources.add("navbar")
                        footer_services = _extract_footer_services_bs4(home_html)
                        if footer_services:
                            found_services.update(footer_services)
                            service_sources.add("footer")
                        if should_extract_contact:
                            found_phones.update(_extract_phones_with_bs4(home_html))
                        navbar_services_found = not _is_weak_service_set(found_services)

                    # Step 2: email pages (excluding homepage), fetched concurrently.
                    email_urls = [urljoin(base_site + "/", p) for p in email_paths if p]
                    if email_urls:
                        if stop_on_first_email:
                            for url in email_urls:
                                html, http_status, final_url = await _fetch_html(session, url)
                                if http_status is not None:
                                    last_http_status = http_status
                                if final_url:
                                    last_final_url = final_url
                                if html:
                                    found_emails.update(_extract_emails_with_bs4(html))
                                    if should_extract_contact:
                                        found_phones.update(_extract_phones_with_bs4(html))
                                if found_emails:
                                    break
                        else:
                            email_tasks = [_fetch_html(session, u) for u in email_urls]
                            email_results = await asyncio.gather(*email_tasks)
                            for html, http_status, final_url in email_results:
                                if http_status is not None:
                                    last_http_status = http_status
                                if final_url:
                                    last_final_url = final_url
                                if html:
                                    found_emails.update(_extract_emails_with_bs4(html))
                                    if should_extract_contact:
                                        found_phones.update(_extract_phones_with_bs4(html))

                    # Step 3: if no navbar services, scrape service/product pages.
                    if not navbar_services_found:
                        service_urls = [urljoin(base_site + "/", p) for p in service_paths]
                        service_tasks = [_fetch_html(session, u) for u in service_urls]
                        service_results = await asyncio.gather(*service_tasks)
                        for html, http_status, final_url in service_results:
                            if http_status is not None:
                                last_http_status = http_status
                            if final_url:
                                last_final_url = final_url
                            if html:
                                page_services = _extract_services_from_page_bs4(html)
                                if page_services:
                                    found_services.update(page_services)
                                    service_sources.add("service_page")
                                if should_extract_contact:
                                    found_phones.update(_extract_phones_with_bs4(html))
                        # Re-evaluate after fallback pages.
                        navbar_services_found = not _is_weak_service_set(found_services)

                    # Break early if we already have both outcomes.
                    if found_emails and found_services:
                        break
    except asyncio.TimeoutError:
        result["status"] = "timeout"
        result["error"] = "Request timeout"
    except Exception as exc:
        result["status"] = "request_failed"
        result["error"] = str(exc)

    if selenium_fallback and (not found_emails or not found_services) and result["status"] == "success":
        try:
            from selenium_extractor import extract_emails_and_services_with_selenium
            for base_site in website_candidates:
                sel_emails, sel_services = await asyncio.to_thread(
                    extract_emails_and_services_with_selenium,
                    base_site
                )
                if sel_emails:
                    found_emails.update(sel_emails)
                if sel_services:
                    found_services.update(sel_services)
                    service_sources.add("selenium")
                if sel_emails or sel_services:
                    result["selenium_fallback_used"] = True
                if found_emails and found_services:
                    break
        except Exception:
            pass

    if found_emails:
        sorted_emails = sorted(found_emails)
        result["emails"] = ", ".join(sorted_emails)
        result["email_count"] = len(sorted_emails)
    elif result["status"] == "success":
        result["status"] = "no_emails"

    if found_services:
        sorted_services = sorted(found_services)
        result["services"] = ", ".join(sorted_services)
        result["service_count"] = len(sorted_services)
        if service_sources:
            result["services_source"] = ", ".join(sorted(service_sources))

    if should_extract_contact and found_phones:
        result["phone"] = ", ".join(sorted(found_phones))

    result["http_status"] = last_http_status
    result["final_url"] = last_final_url
    result["duration_sec"] = round(asyncio.get_running_loop().time() - started, 2)
    return result


async def _run_email_extraction_bs4_async(
    df_input,
    progress_callback=None,
    status_callback=None,
    *,
    chunk_size=25,
    max_concurrent_sites=20,
    max_connections=80,
    request_timeout=12,
    paths=None,
    selenium_fallback=False,
    bs4_enabled=True,
    stop_on_first_email=False,
):
    import pandas as pd

    total = len(df_input)
    if total == 0:
        return pd.DataFrame([])

    email_paths = paths or DEFAULT_PATHS
    service_paths = SERVICE_PATHS
    timeout = aiohttp.ClientTimeout(total=request_timeout)
    connector = aiohttp.TCPConnector(limit=max_connections, ssl=False)
    semaphore = asyncio.Semaphore(max_concurrent_sites)
    results_by_row_idx = {}
    completed = 0

    row_lookup = {
        int(row["_row_idx"]): row
        for _, row in df_input.iterrows()
        if "_row_idx" in row
    }

    async with aiohttp.ClientSession(
        timeout=timeout,
        headers=HEADERS,
        connector=connector,
    ) as session:
        async def _run_dedup_member_group(rep_row, member_row_idxs):
            result = await _extract_emails_one_site(
                rep_row,
                session,
                semaphore,
                email_paths,
                service_paths,
                selenium_fallback=selenium_fallback,
                bs4_enabled=bs4_enabled,
                stop_on_first_email=stop_on_first_email,
            )
            return member_row_idxs, result

        for chunk_start in range(0, total, chunk_size):
            chunk_df = df_input.iloc[chunk_start:chunk_start + chunk_size]
            dedup = {}
            for _, row in chunk_df.iterrows():
                website = row.get("website")
                if not isinstance(website, str) or not website.startswith("http"):
                    dedup[("invalid", int(row.get("_row_idx", -1)))] = {
                        "rep_row": row,
                        "members": [int(row.get("_row_idx", -1))],
                    }
                    continue
                norm_site = website.strip().lower().rstrip("/")
                needs_contact = _is_blank_value(row.get("contact")) and _is_blank_value(row.get("phone"))
                key = (norm_site, needs_contact)
                if key not in dedup:
                    dedup[key] = {"rep_row": row, "members": []}
                dedup[key]["members"].append(int(row.get("_row_idx", -1)))

            tasks = []
            for key, info in dedup.items():
                rep_row = info["rep_row"]
                task = asyncio.create_task(
                    _run_dedup_member_group(
                        rep_row,
                        info["members"],
                    )
                )
                tasks.append(task)

            for task in asyncio.as_completed(tasks):
                member_row_idxs, result = await task

                for member_idx in member_row_idxs:
                    orig = row_lookup.get(member_idx)
                    if orig is None:
                        continue

                    member_result = dict(result)
                    member_result["_row_idx"] = member_idx
                    member_result["name"] = orig.get("name")
                    member_result["address"] = orig.get("address")
                    member_result["website"] = orig.get("website")

                    # Preserve existing phone/contact unless the row was blank and we scraped one.
                    orig_phone = orig.get("phone")
                    orig_contact = orig.get("contact")
                    if _is_blank_value(orig_phone):
                        if _is_blank_value(orig_contact):
                            pass  # keep scraped phone (if any)
                        else:
                            member_result["phone"] = orig_contact
                    else:
                        member_result["phone"] = orig_phone

                    results_by_row_idx[member_idx] = member_result

                    if status_callback:
                        name = member_result.get("name") or "Unknown Company"
                        status = member_result.get("status")
                        email_count = member_result.get("email_count")
                        service_count = member_result.get("service_count")
                        duration = member_result.get("duration_sec")
                        fallback_used = member_result.get("selenium_fallback_used")
                        suffix = " [selenium]" if fallback_used else ""
                        status_callback(
                            f"{name} -> {status} (emails={email_count}, services={service_count}, {duration}s){suffix}"
                        )

                completed += len(member_row_idxs)

                if progress_callback:
                    progress_callback(completed / total)

    ordered_idxs = sorted(results_by_row_idx.keys())
    ordered_results = [results_by_row_idx[idx] for idx in ordered_idxs]
    return pd.DataFrame(ordered_results)


def run_email_extraction_bs4_async(
    df_input,
    progress_callback=None,
    status_callback=None,
    *,
    chunk_size=25,
    max_concurrent_sites=20,
    max_connections=80,
    request_timeout=12,
    paths=None,
    retry_no_emails_with_selenium=True,
    max_selenium_retry_rows=None,
    retry_no_services_with_selenium=True,
    max_selenium_service_retry_rows=None,
    stop_on_first_email=False,
    include_debug_columns=False,
):
    """Two-stage pipeline: BS4 pass first, Selenium retry for no_emails rows, then drop unresolved no_emails."""

    df_work = df_input.copy().reset_index(drop=True)
    df_work["_row_idx"] = range(len(df_work))

    async def _two_stage():
        first_pass = await _run_email_extraction_bs4_async(
            df_work,
            progress_callback=progress_callback,
            status_callback=status_callback,
            chunk_size=chunk_size,
            max_concurrent_sites=max_concurrent_sites,
            max_connections=max_connections,
            request_timeout=request_timeout,
            paths=paths,
            selenium_fallback=False,
            bs4_enabled=True,
            stop_on_first_email=stop_on_first_email,
        )

        if first_pass.empty or not retry_no_emails_with_selenium:
            return first_pass

        retry_rows = first_pass[first_pass["status"] == "no_emails"].copy()
        if retry_rows.empty:
            return first_pass

        if isinstance(max_selenium_retry_rows, int) and max_selenium_retry_rows > 0:
            retry_rows = retry_rows.head(max_selenium_retry_rows)
            if retry_rows.empty:
                return first_pass

        retry_total = len(retry_rows)
        if status_callback:
            status_callback(
                f"[retry-stage] Retrying {retry_total} no_emails rows with Selenium extractor..."
            )

        retry_input = retry_rows[["name", "address", "phone", "website", "_row_idx"]].copy()
        retry_status_callback = None
        if status_callback:
            retry_counter = {"done": 0}

            def retry_status_callback(msg):
                retry_counter["done"] += 1
                status_callback(f"[retry {retry_counter['done']}/{retry_total}] {msg}")
        retry_pass = await _run_email_extraction_bs4_async(
            retry_input,
            progress_callback=None,
            status_callback=retry_status_callback,
            chunk_size=chunk_size,
            max_concurrent_sites=max_concurrent_sites,
            max_connections=max_connections,
            request_timeout=request_timeout,
            paths=paths,
            selenium_fallback=True,
            bs4_enabled=False,
            stop_on_first_email=stop_on_first_email,
        )

        merged = first_pass.set_index("_row_idx")
        retry_indexed = retry_pass.set_index("_row_idx")
        merged.update(retry_indexed)
        merged_df = merged.sort_index().reset_index()

        # Optional second retry pass for rows that have email but no services.
        if retry_no_services_with_selenium and not merged_df.empty:
            service_retry_rows = merged_df[
                (merged_df["status"] != "no_emails")
                & (merged_df["service_count"].fillna(0) == 0)
            ].copy()

            if isinstance(max_selenium_service_retry_rows, int) and max_selenium_service_retry_rows > 0:
                service_retry_rows = service_retry_rows.head(max_selenium_service_retry_rows)

            if not service_retry_rows.empty:
                service_retry_total = len(service_retry_rows)
                if status_callback:
                    status_callback(
                        f"[retry-stage] Retrying {service_retry_total} no_services rows with Selenium extractor..."
                    )

                service_retry_input = service_retry_rows[
                    ["name", "address", "phone", "website", "_row_idx"]
                ].copy()

                service_retry_status_callback = None
                if status_callback:
                    service_retry_counter = {"done": 0}

                    def service_retry_status_callback(msg):
                        service_retry_counter["done"] += 1
                        status_callback(
                            f"[retry {service_retry_counter['done']}/{service_retry_total}] {msg}"
                        )

                service_retry_pass = await _run_email_extraction_bs4_async(
                    service_retry_input,
                    progress_callback=None,
                    status_callback=service_retry_status_callback,
                    chunk_size=chunk_size,
                    max_concurrent_sites=max_concurrent_sites,
                    max_connections=max_connections,
                    request_timeout=request_timeout,
                    paths=paths,
                    selenium_fallback=True,
                    bs4_enabled=False,
                    stop_on_first_email=stop_on_first_email,
                )

                merged2 = merged_df.set_index("_row_idx")
                service_retry_indexed = service_retry_pass.set_index("_row_idx")
                merged2.update(service_retry_indexed)
                merged_df = merged2.sort_index().reset_index()

        return merged_df

    coro = _two_stage()
    try:
        result_df = asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            result_df = loop.run_until_complete(coro)
        finally:
            loop.close()

    if "_row_idx" in result_df.columns:
        result_df = result_df.drop(columns=["_row_idx"])

    # Keep only rows where at least one email was extracted after BS4 + Selenium retry.
    if "status" in result_df.columns:
        result_df = result_df[result_df["status"] != "no_emails"].reset_index(drop=True)

    output_columns = ["name", "address", "phone", "website", "emails", "services"]
    if include_debug_columns:
        output_columns.append("services_source")
    for col in output_columns:
        if col not in result_df.columns:
            result_df[col] = None
    return result_df[output_columns].copy()


# Backward-compatible alias for existing app integrations.
run_site_visit_async = run_email_extraction_bs4_async
