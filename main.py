from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime

import httpx
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse, parse_qs
from typing import List, Dict, Any, Tuple

from playwright.sync_api import sync_playwright

# ---------- CONSTANTS ----------

RAW_HTML_MAX_CHARS = 5000
TEXT_LENGTH_JS_THRESHOLD = 500
PLAYWRIGHT_SCROLL_TIMES = 3

# ---------- APP & TEMPLATES ----------

app = FastAPI()
templates = Jinja2Templates(directory="templates")
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------- MODELS ----------

class ScrapeRequest(BaseModel):
    url: str


# ---------- HELPERS ----------

def fetch_html(url: str) -> str | None:
    """
    Fetch HTML of the given URL using httpx (static request),
    with a browser-like User-Agent to reduce 403 errors.
    Returns HTML text, or None if fetch fails.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    try:
        with httpx.Client(timeout=15.0, follow_redirects=True, headers=headers) as client:
            response = client.get(url)
            response.raise_for_status()
            return response.text
    except httpx.HTTPError:
        # If anything goes wrong, just return None.
        return None


def render_with_playwright(url: str) -> Tuple[str | None, Dict[str, Any]]:
    """
    Render the page with Playwright (scroll, click, pagination).
    Returns (html, interactions).
    """
    interactions = {
        "clicks": [],
        "scrolls": 0,
        "pages": [url],
    }

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                locale="en-US",
            )
            page = context.new_page()

            # Helper: load a page and wait for JS/network to settle
            def load_page(u: str):
                page.goto(u, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(800)

            # --- PAGE 1 ---
            load_page(url)

            # SCROLL DEPTH ≥ 3
            for _ in range(PLAYWRIGHT_SCROLL_TIMES):
                page.mouse.wheel(0, 2000)
                page.wait_for_timeout(1500)
                interactions["scrolls"] += 1

            # BASIC CLICK FLOW: Load more / Show more
            load_more_selectors = [
                "button:has-text('Load more')",
                "button:has-text('Show more')",
                "a:has-text('Load more')",
                "a:has-text('Show more')",
            ]

            for selector in load_more_selectors:
                buttons = page.query_selector_all(selector)
                if buttons:
                    buttons[0].click()
                    interactions["clicks"].append(selector)
                    page.wait_for_timeout(2000)
                    break

            # TAB CLICK FLOW
            try:
                tabs = page.query_selector_all("[role='tab']")
                if tabs:
                    tabs[0].click()
                    interactions["clicks"].append("tab: [role='tab']")
                    page.wait_for_timeout(1500)
            except Exception:
                pass

            # PAGINATION DEPTH ≥ 3: follow "Next" or numbered (?page=N) links
            MAX_PAGES = 3  # Page1 + Page2 + Page3
            while len(interactions["pages"]) < MAX_PAGES:
                next_link = None

                # 1) Try explicit "next" selectors
                next_selectors = [
                    "a[rel='next']",
                    "a:has-text('Next')",
                    "a:has-text('›')",
                    "a:has-text('>>')",
                    "button:has-text('Next')",
                ]

                for sel in next_selectors:
                    candidate = page.query_selector(sel)
                    if candidate:
                        next_link = candidate.get_attribute("href")
                        break

                # 2) If no explicit "next", try numbered pagination via ?page=N
                if not next_link:
                    current_url = page.url
                    parsed_current = urlparse(current_url)
                    qs_current = parse_qs(parsed_current.query)

                    current_page_num = 1
                    try:
                        if "page" in qs_current:
                            current_page_num = int(qs_current["page"][0])
                    except Exception:
                        current_page_num = 1

                    candidate_next_url = None
                    candidate_next_page_num: int | None = None

                    for a in page.query_selector_all("a[href]"):
                        href = a.get_attribute("href") or ""
                        absolute = urljoin(current_url, href)
                        parsed = urlparse(absolute)
                        qs = parse_qs(parsed.query)

                        if "page" not in qs:
                            continue

                        try:
                            pnum = int(qs["page"][0])
                        except Exception:
                            continue

                        # choose the smallest page number > current_page_num
                        if pnum > current_page_num and (
                            candidate_next_page_num is None
                            or pnum < candidate_next_page_num
                        ):
                            candidate_next_page_num = pnum
                            candidate_next_url = absolute

                    if candidate_next_url:
                        next_link = candidate_next_url

                # If we still don't have any candidate, stop pagination
                if not next_link:
                    break

                # Resolve relative URL to absolute
                next_url = urljoin(page.url, next_link)

                # Avoid loops
                if next_url in interactions["pages"]:
                    break

                # Visit next page
                load_page(next_url)
                interactions["pages"].append(next_url)

                # Let content load on next pages too
                page.wait_for_timeout(1000)

            # Return rendered HTML of the LAST page visited
            html = page.content()
            current_url = page.url
            if current_url not in interactions["pages"]:
                interactions["pages"].append(current_url)

            browser.close()
            return html, interactions

    except Exception:
        return None, interactions




def extract_meta(url: str, soup: BeautifulSoup) -> Dict[str, Any]:
    # Title
    title_tag = soup.find("title")
    og_title = soup.find("meta", property="og:title")
    title = ""
    if og_title and og_title.get("content"):
        title = og_title["content"].strip()
    elif title_tag and title_tag.text:
        title = title_tag.text.strip()

    # Description
    desc = ""
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if meta_desc and meta_desc.get("content"):
        desc = meta_desc["content"].strip()

    # Language
    html_tag = soup.find("html")
    lang = html_tag.get("lang", "").strip() if html_tag else ""

    # Canonical
    canonical_link = soup.find("link", rel="canonical")
    canonical = canonical_link.get("href").strip() if canonical_link and canonical_link.get("href") else None

    # Make canonical absolute if available
    if canonical:
        canonical = urljoin(url, canonical)

    return {
        "title": title or "",
        "description": desc or "",
        "language": lang or "",
        "canonical": canonical,
    }


def extract_sections(url: str, soup: BeautifulSoup) -> List[Dict[str, Any]]:
    sections: List[Dict[str, Any]] = []

    # Prefer <main>, else <body>
    container = soup.find("main") or soup.find("body")
    if not container:
        return sections

    # Find major blocks: header, nav, section, footer, article
    candidates = container.find_all(
        ["header", "nav", "section", "footer", "article"],
        recursive=False
    )

    # If we find nothing, treat the whole container as one section
    if not candidates:
        candidates = [container]

    for idx, elem in enumerate(candidates):
        # Headings
        heading_tags = elem.find_all(["h1", "h2", "h3"])
        headings = [h.get_text(strip=True) for h in heading_tags if h.get_text(strip=True)]

        # Text content
        text = elem.get_text(separator=" ", strip=True)

        # Links
        links = []
        for a in elem.find_all("a", href=True):
            href = urljoin(url, a["href"])
            link_text = a.get_text(strip=True)
            links.append({"text": link_text, "href": href})

        # Images
        images = []
        for img in elem.find_all("img", src=True):
            src = urljoin(url, img["src"])
            alt = img.get("alt", "")
            images.append({"src": src, "alt": alt})

        # Lists
        lists: List[List[str]] = []
        for ul in elem.find_all(["ul", "ol"]):
            items = [li.get_text(strip=True) for li in ul.find_all("li")]
            if items:
                lists.append(items)

        # Tables (simple: list of rows, each row is list of cell text)
        tables: List[Any] = []
        for table in elem.find_all("table"):
            rows: List[List[str]] = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)

        # Raw HTML (truncated)
        raw_html = str(elem)
        truncated = False
        if len(raw_html) > RAW_HTML_MAX_CHARS:
            raw_html = raw_html[:RAW_HTML_MAX_CHARS] + "...[truncated]"
            truncated = True

        # Determine type
        tag_name = elem.name
        if tag_name == "header":
            section_type = "hero"
        elif tag_name == "nav":
            section_type = "nav"
        elif tag_name == "footer":
            section_type = "footer"
        else:
            section_type = "section"

        # Label: first heading or first 5–7 words of text
        if headings:
            label = headings[0]
        else:
            words = text.split()
            label = " ".join(words[:7]) if words else "Section"

        section = {
            "id": f"{section_type}-{idx}",
            "type": section_type,
            "label": label,
            "sourceUrl": url,
            "content": {
                "headings": headings,
                "text": text,
                "links": links,
                "images": images,
                "lists": lists,
                "tables": tables,
            },
            "rawHtml": raw_html,
            "truncated": truncated,
        }

        # Only add sections with some meaningful content
        if text or links or images or lists or tables:
            sections.append(section)

    return sections


def build_result(
    url: str,
    meta: Dict[str, Any],
    sections: List[Dict[str, Any]],
    interactions: Dict[str, Any],
    errors: List[Dict[str, str]],
) -> Dict[str, Any]:
    return {
        "result": {
            "url": url,
            "scrapedAt": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "meta": meta,
            "sections": sections,
            "interactions": interactions,
            "errors": errors,
        }
    }


# ---------- ROUTES ----------

@app.get("/healthz")
def health_check():
    return {"status": "ok"}


@app.get("/")
def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/scrape")
def scrape_website(request: ScrapeRequest):
    errors: List[Dict[str, str]] = []

    if not (request.url.startswith("http://") or request.url.startswith("https://")):
        errors.append({
            "message": "URL must start with http:// or https://",
            "phase": "fetch"
        })
        empty_meta = {"title": "", "description": "", "language": "", "canonical": None}
        empty_interactions = {"clicks": [], "scrolls": 0, "pages": []}
        return build_result(request.url, empty_meta, [], empty_interactions, errors)

    # ---------- STATIC SCRAPING FIRST ----------
    html = fetch_html(request.url)
    static_failed = html is None  # remember if static did fail

    meta: Dict[str, Any] = {
        "title": "",
        "description": "",
        "language": "",
        "canonical": None,
    }
    sections: List[Dict[str, Any]] = []
    interactions = {
        "clicks": [],
        "scrolls": 0,
        "pages": [request.url],
    }

    if not static_failed:
        soup = BeautifulSoup(html, "html.parser")
        meta = extract_meta(request.url, soup)
        sections = extract_sections(request.url, soup)

    # ---------- DECIDE IF WE NEED JS FALLBACK ----------
    total_text_len = sum(len(sec["content"]["text"]) for sec in sections)
    use_js_fallback = static_failed or (total_text_len < TEXT_LENGTH_JS_THRESHOLD)

    if use_js_fallback:
        html_js, interactions_js = render_with_playwright(request.url)
        if html_js is not None:
            soup_js = BeautifulSoup(html_js, "html.parser")
            meta = extract_meta(request.url, soup_js)
            sections = extract_sections(request.url, soup_js)
            interactions = interactions_js
            # JS succeeded → we *don't* add a static error, even if static failed
        else:
            # JS also failed
            if static_failed:
                errors.append({
                    "message": "Static fetch failed (blocked, 4xx/5xx, or network error).",
                    "phase": "fetch"
                })
            errors.append({
                "message": "JS fallback with Playwright failed.",
                "phase": "render"
            })

    # Fallback section if still nothing but no hard failure
    if not sections and not errors:
        body_text = ""
        body_html = ""
        if html:
            soup_fallback = BeautifulSoup(html, "html.parser")
            body = soup_fallback.find("body")
            body_text = body.get_text(separator=" ", strip=True) if body else ""
            body_html = str(body) if body else ""

        truncated = False
        if len(body_html) > RAW_HTML_MAX_CHARS:
            body_html = body_html[:RAW_HTML_MAX_CHARS] + "...[truncated]"
            truncated = True

        sections = [
            {
                "id": "section-0",
                "type": "section",
                "label": "Page Content",
                "sourceUrl": request.url,
                "content": {
                    "headings": [],
                    "text": body_text,
                    "links": [],
                    "images": [],
                    "lists": [],
                    "tables": [],
                },
                "rawHtml": body_html,
                "truncated": truncated,
            }
        ]

    return build_result(request.url, meta, sections, interactions, errors)

