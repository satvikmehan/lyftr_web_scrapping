# Universal Website Scraper

This project implements the assignment requirements for building a universal website scraper that supports both static and JavaScript-rendered pages, performs basic click flows, handles scroll-based pagination depth ≥ 3, and outputs section-aware structured JSON. A minimal frontend UI is included to input URLs and inspect the JSON output.

This scraper is intentionally designed as an MVP with a clear, simple architecture that meets the functional requirements while remaining easy to review and extend.


# How to Run
Step 1 — Make the startup script executable
chmod +x run.sh

Step 2 — Run the scraper
./run.sh

This script will:

Create & activate a virtual environment

Install Python dependencies

Install Playwright browsers

Start FastAPI on http://localhost:8000



# Test URLs Used

You can replace these with URLs you actually used, but here is a suggested list:

Static page
https://example.com

JS-rendered SPA page
https://nextjs.org/

Infinite scroll / dynamic loading
https://unsplash.com/

These demonstrate static scraping, JS fallback, scroll depth, and dynamic content loading


# Limitations 

Does not implement pagination via next-page links (?page=2)

Does not click tabs (role="tab") — only load-more flows

Does not perform advanced noise removal (cookie banners, modals)

Basic heuristics used for section detection, not ML-based classification

JS-rendered sites may occasionally block scraping (cloudflare, bot protection)


# Core Capabilities

1. Scrape both static and JS-rendered pages

Static scraping is attempted first using httpx + BeautifulSoup.

If the page appears incomplete or static fetch fails, the system automatically falls back to Playwright, loading the full JS-rendered DOM using a headless Chromium browser.

2. Perform a basic click flow

The scraper looks for common UI triggers:

“Load more”

“Show more”

If found, it clicks the first matching button to reveal additional content.

3. Support scroll/pagination depth ≥ 3

Playwright performs three scroll events, allowing pages with infinite scroll or lazy-loaded content to reveal more items.

All visited URLs and interactions are recorded.

4. Return section-aware structured JSON (assignment schema)

For each scrape, the backend returns:

Meta: title, description, canonical URL, language

Sections:

Each is extracted based on semantic HTML tags (header, section, nav, article, footer)

Includes headings, text, links, images, lists, tables

Includes truncated raw HTML with "truncated": true when applicable

Interactions: scroll count, click selectors, visited URLs

Errors: non-fatal failures described by phase (fetch, render)

Always responds with HTTP 200 and a consistent JSON envelope.

5. Minimal frontend for viewing/downloading JSON

A small UI is served at GET /

Users can:

Enter a URL

Trigger a scrape

View meta, interactions, and sections

Expand each section's JSON

Download the full scrape result



# Architecture Overview
FastAPI backend
│
├── Static scrape (httpx → BeautifulSoup)
├── Heuristic check (content size < threshold?)
├── JS fallback (Playwright → Chromium headless)
│   ├── Scroll 3 times
│   ├── Click Load more / Show more
│   ├── Record interactions
│   └── Extract DOM
│
└── HTML parsing → Section JSON schema

# Project Structure
.
├── main.py
├── run.sh
├── requirements.txt
├── README.md
├── design_notes.md        ← required by assignment
├── capabilities.json       ← required by assignment
├── templates/
│   └── index.html          ← minimal JSON viewer
├── static/
│   └── (optional assets



