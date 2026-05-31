import http.server
import socketserver
import urllib.request
import urllib.parse
import json
import sqlite3
import re
import os
import threading
import time
import csv
import datetime
import math

PORT = 8000
DB_FILE = "jobs.db"
LOCK = threading.Lock()

PRESEED_ATS_COMPANIES = [
    ("Monzo", "greenhouse", "monzo"),
    ("Deliveroo", "greenhouse", "deliveroo"),
    ("Revolut", "lever", "revolut"),
    ("Wise", "greenhouse", "transferwise"),
    ("Starling Bank", "greenhouse", "starlingbank"),
    ("Snyk", "greenhouse", "snyk"),
    ("Checkout.com", "greenhouse", "checkout"),
    ("Improbable", "greenhouse", "improbable"),
    ("Skyscanner", "greenhouse", "skyscanner"),
    ("Gousto", "greenhouse", "gousto"),
    ("Gymshark", "greenhouse", "gymshark"),
    ("Curve", "greenhouse", "curve"),
    ("Cleo", "greenhouse", "cleo"),
    ("Octopus Energy", "greenhouse", "octopusenergy"),
    ("DeepMind", "greenhouse", "deepmind"),
    ("Graphcore", "greenhouse", "graphcore"),
    ("Hadean", "greenhouse", "hadean"),
    ("TrueLayer", "greenhouse", "truelayer"),
    ("Zego", "greenhouse", "zego"),
    ("Marshmallow", "greenhouse", "marshmallow"),
    ("Farewill", "greenhouse", "farewill"),
    ("Bloom & Wild", "greenhouse", "bloomandwild"),
    ("Paddle", "greenhouse", "paddle"),
    ("Motorway", "greenhouse", "motorway"),
    ("Depop", "greenhouse", "depop"),
    ("Lyst", "greenhouse", "lyst"),
    ("Trainline", "greenhouse", "trainline"),
    ("Zilch", "greenhouse", "zilch"),
    ("Thought Machine", "greenhouse", "thoughtmachine"),
    ("PrimaryBid", "greenhouse", "primarybid"),
    ("Wayve", "greenhouse", "wayve"),
    ("Synthesia", "greenhouse", "synthesia"),
    ("Onfido", "greenhouse", "onfido"),
    ("ComplyAdvantage", "greenhouse", "complyadvantage"),
    ("Multiverse", "greenhouse", "multiverse"),
    ("Snowplow", "greenhouse", "snowplow"),
    ("Faculty", "greenhouse", "faculty"),
    ("Signal AI", "greenhouse", "signalai"),
    ("Healx", "greenhouse", "healx"),
    ("BrewDog", "greenhouse", "brewdog")
]

def clean_value(val):
    if not val:
        return ""
    val = val.strip()
    if len(val) >= 2 and val[0] == '"' and val[-1] == '"':
        val = val[1:-1].strip()
    return val

def db_init():
    """Initializes the database schema and indexes."""
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. Create sponsors table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sponsors (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        organisation_name TEXT,
        town_city TEXT,
        county TEXT,
        rating TEXT,
        route TEXT,
        website_url TEXT,
        careers_url TEXT,
        status TEXT,
        date_added TEXT,
        last_seen TEXT
    )
    """)
    
    # 2. Create sync_history table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sync_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sync_date TEXT,
        csv_url TEXT,
        added_count INTEGER,
        removed_count INTEGER,
        total_sponsors INTEGER
    )
    """)
    
    # 3. Create jobs table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        sponsor_id INTEGER,
        company_name TEXT,
        job_title TEXT,
        department TEXT,
        location TEXT,
        job_url TEXT,
        posted_date TEXT,
        source TEXT,
        raw_id TEXT UNIQUE,
        FOREIGN KEY(sponsor_id) REFERENCES sponsors(id) ON DELETE SET NULL
    )
    """)
    
    # 4. Create sponsor_ats_mappings table
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sponsor_ats_mappings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        company_name TEXT UNIQUE,
        ats_type TEXT,
        ats_token TEXT
    )
    """)
    
    # Indexes for ultra-fast query execution
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_name ON sponsors(organisation_name COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_city ON sponsors(town_city COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_route ON sponsors(route COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_status ON sponsors(status)")
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(job_title COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dept ON jobs(department COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_loc ON jobs(location COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name)")
    
    # Preseed initial ATS mappings
    for name, ats_type, token in PRESEED_ATS_COMPANIES:
        try:
            cursor.execute("""
            INSERT OR IGNORE INTO sponsor_ats_mappings (company_name, ats_type, ats_token)
            VALUES (?, ?, ?)
            """, (name, ats_type, token))
        except Exception as e:
            pass
            
    conn.commit()
    conn.close()
    print("[Database] Standalone schema initialized successfully.")

# ---------------------------------------------------------------------------
# WEB CRAWLER & SEARCH ENGINE UTILITIES
# ---------------------------------------------------------------------------

def search_duckduckgo(query):
    """Performs a search on DuckDuckGo HTML search and returns non-DDG result URLs."""
    url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote(query)
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        links = re.findall(r'href="([^"]+?)"', html)
        discovered = []
        for link in links:
            # Skip duckduckgo specific links
            if "duckduckgo.com" not in link and (link.startswith("http://") or link.startswith("https://") or "/l/?kh=-1&uddg=" in link):
                # Unpack DuckDuckGo redirect link if present
                if "/l/?kh=-1&uddg=" in link:
                    query_params = urllib.parse.parse_qs(urllib.parse.urlparse(link).query)
                    if "uddg" in query_params:
                        link = query_params["uddg"][0]
                discovered.append(link)
        return discovered
    except Exception as e:
        print(f"[Crawler Search] DDG Query failed for '{query}': {e}")
        return []

def auto_discover_careers_url(company_name, city):
    """Automatically finds the career webpage for a company using DDG."""
    query = f"{company_name} {city} UK official website careers jobs"
    links = search_duckduckgo(query)
    
    # Filter social media and third-party links
    filtered_links = []
    for link in links:
        link_lower = link.lower()
        if any(x in link_lower for x in ["facebook.com", "twitter.com", "linkedin.com", "instagram.com", "youtube.com", "gov.uk", "sponsorship", "glassdoor", "indeed", "companieshouse", "wikipedia.org"]):
            continue
        filtered_links.append(link)
        
    if filtered_links:
        # Prefer urls with careers/jobs keywords
        for link in filtered_links:
            if any(k in link.lower() for k in ["career", "job", "work-with-us", "vacancy", "join-us", "position"]):
                return link
        return filtered_links[0]
    return ""

# ---------------------------------------------------------------------------
# "SPONSOR WEB RADAR" SPIDER (CRAWLERS)
# ---------------------------------------------------------------------------

def crawl_greenhouse(company_name, token, sponsor_id=None):
    """Crawls active jobs from Greenhouse Board API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    jobs_added = 0
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        if "jobs" not in data:
            return 0
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        # Pull sponsor_id if not supplied
        if not sponsor_id:
            cursor.execute("SELECT id FROM sponsors WHERE organisation_name LIKE ? LIMIT 1", (f"%{company_name}%",))
            row = cursor.fetchone()
            sponsor_id = row[0] if row else None
            
        today_str = datetime.date.today().isoformat()
        
        # Save each job
        for item in data["jobs"]:
            raw_id = f"greenhouse-{item['id']}"
            title = clean_value(item.get("title", ""))
            job_url = clean_value(item.get("absolute_url", ""))
            
            # Location
            loc_data = item.get("location", {})
            location = loc_data.get("name", "UK") if loc_data else "UK"
            
            # Skip if location is explicitly outside UK
            if any(non_uk in location.lower() for non_uk in ["usa", "canada", "germany", "france", "india", "australia"]) and "united kingdom" not in location.lower() and "london" not in location.lower():
                continue
                
            # Department
            depts = item.get("departments", [])
            department = depts[0].get("name", "General") if depts else "General"
            
            cursor.execute("""
            INSERT OR REPLACE INTO jobs (sponsor_id, company_name, job_title, department, location, job_url, posted_date, source, raw_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Greenhouse API', ?)
            """, (sponsor_id, company_name, title, department, location, job_url, today_str, raw_id))
            jobs_added += 1
            
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Spider] Greenhouse crawl failed for '{company_name}': {e}")
        
    return jobs_added

def crawl_lever(company_name, token, sponsor_id=None):
    """Crawls active jobs from Lever Posting API."""
    url = f"https://api.lever.co/v0/postings/{token}?group=team"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    jobs_added = 0
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode('utf-8'))
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        if not sponsor_id:
            cursor.execute("SELECT id FROM sponsors WHERE organisation_name LIKE ? LIMIT 1", (f"%{company_name}%",))
            row = cursor.fetchone()
            sponsor_id = row[0] if row else None
            
        today_str = datetime.date.today().isoformat()
        
        # Lever response groups postings by team/dept
        for group in data:
            dept_name = group.get("title", "General")
            postings = group.get("postings", [])
            
            for item in postings:
                raw_id = f"lever-{item['id']}"
                title = clean_value(item.get("title", ""))
                job_url = clean_value(item.get("hostedUrl", ""))
                
                categories = item.get("categories", {})
                location = categories.get("location", "UK")
                
                # Check for UK positions only
                if any(non_uk in location.lower() for non_uk in ["usa", "us", "germany", "india", "berlin", "remote us"]) and "london" not in location.lower() and "united kingdom" not in location.lower() and "uk" not in location.lower():
                    continue
                    
                cursor.execute("""
                INSERT OR REPLACE INTO jobs (sponsor_id, company_name, job_title, department, location, job_url, posted_date, source, raw_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Lever API', ?)
                """, (sponsor_id, company_name, title, dept_name, location, job_url, today_str, raw_id))
                jobs_added += 1
                
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Spider] Lever crawl failed for '{company_name}': {e}")
        
    return jobs_added

def scrape_custom_website(company_name, careers_url, sponsor_id=None):
    """Scrapes raw job vacancies directly from a custom HTML careers page."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
    jobs_added = 0
    
    try:
        req = urllib.request.Request(careers_url, headers=headers)
        with urllib.request.urlopen(req, timeout=12) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        # Parse base domain to resolve relative paths
        parsed_base = urllib.parse.urlparse(careers_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
        
        # Regex to scan all anchor links
        anchors = re.findall(r'<a\s+[^>]*?href=["\']([^"\']+)["\'][^>]*?>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
        
        today_str = datetime.date.today().isoformat()
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        if not sponsor_id:
            cursor.execute("SELECT id FROM sponsors WHERE organisation_name LIKE ? LIMIT 1", (f"%{company_name}%",))
            row = cursor.fetchone()
            sponsor_id = row[0] if row else None
            
        seen_urls = set()
        
        # High probability job keywords
        job_keywords = ["engineer", "developer", "designer", "manager", "nurse", "analyst", "operator", "consultant", "technician", 
                        "lead", "director", "writer", "architect", "support", "intern", "graduate", "specialist", "associate"]
                        
        for href, text in anchors:
            # Clean anchor text from HTML tags
            text_clean = re.sub(r'<[^>]+>', '', text).strip()
            text_clean = re.sub(r'\s+', ' ', text_clean)
            
            href = href.strip()
            if not href or not text_clean:
                continue
                
            # Filter anchor text matching job keywords or href matching job routes
            text_lower = text_clean.lower()
            href_lower = href.lower()
            
            is_job = False
            # Option 1: Title contains job role indicators and is relatively short (under 70 chars)
            if len(text_clean) < 70 and any(kw in text_lower for kw in job_keywords):
                is_job = True
            # Option 2: The URL itself matches typical job paths
            elif any(p in href_lower for p in ["/jobs/", "/careers/", "/vacancy/", "/openings/", "/apply/"]):
                if len(text_clean) < 70 and len(text_clean) > 4: # sanity checks
                    is_job = True
                    
            # Skip noise and utility links
            if is_job:
                if any(noise in text_lower for noise in ["sign in", "login", "cookie", "privacy", "about us", "terms", "faq", "contact", "home"]):
                    continue
                if href.startswith("#") or href.startswith("javascript:") or href.startswith("tel:") or href.startswith("mailto:"):
                    continue
                    
                # Standardize relative URLs
                if href.startswith("/"):
                    job_url = base_domain + href
                elif not href.startswith("http"):
                    job_url = careers_url.rstrip("/") + "/" + href
                else:
                    job_url = href
                    
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                
                # Make a unique raw_id
                raw_hash = hash(job_url)
                raw_id = f"spider-{company_name.lower().replace(' ', '-')}-{raw_hash}"
                
                cursor.execute("""
                INSERT OR REPLACE INTO jobs (sponsor_id, company_name, job_title, department, location, job_url, posted_date, source, raw_id)
                VALUES (?, ?, ?, 'Careers Portal', 'UK', ?, ?, 'Web Spider', ?)
                """, (sponsor_id, company_name, text_clean, job_url, today_str, raw_id))
                jobs_added += 1
                
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[Spider] Custom site crawl failed for '{company_name}' at '{careers_url}': {e}")
        
    return jobs_added

# ---------------------------------------------------------------------------
# BACKGROUND SYNC DAEMONS
# ---------------------------------------------------------------------------

def run_sponsors_sync():
    """Incremental GOV.UK CSV sponsorship register sync."""
    db_init()
    print("[Sync] Checking for GOV.UK sponsor register updates...")
    url = "https://www.gov.uk/government/publications/register-of-licensed-sponsors-workers"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    try:
        # 1. Scrape latest CSV URL
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
        
        matches = re.findall(r'href="([^"]+?Worker_and_Temporary_Worker\.csv)"', html)
        if not matches:
            matches = re.findall(r'href="([^"]+?\.csv)"', html)
            
        if not matches:
            print("[Sync] Failed to discover CSV link on GOV.UK page. Aborting.")
            return False
            
        csv_url = matches[0]
        if csv_url.startswith('/'):
            csv_url = "https://www.gov.uk" + csv_url
            
        # 2. Check if already loaded
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM sync_history WHERE csv_url = ?", (csv_url,))
        synced = cursor.fetchone()
        
        cursor.execute("SELECT COUNT(*) FROM sponsors")
        total_in_db = cursor.fetchone()[0]
        
        if synced and total_in_db > 0:
            print("[Sync] Sponsor database is already up to date.")
            conn.close()
            return True
            
        print(f"[Sync] Fetching brand new sponsor register CSV from: {csv_url}")
        csv_req = urllib.request.Request(csv_url, headers=headers)
        with urllib.request.urlopen(csv_req, timeout=60) as csv_resp:
            csv_data = csv_resp.read().decode('utf-8', errors='ignore')
            
        reader = csv.reader(csv_data.splitlines())
        try:
            next(reader) # skip headers
        except StopIteration:
            print("[Sync] Monolithic CSV is empty. Aborting.")
            conn.close()
            return False
            
        # Map current active sponsors to compare incremental diffs
        cursor.execute("SELECT id, organisation_name, town_city, route, status FROM sponsors WHERE status != 'Removed'")
        active_map = {}
        for db_id, name, city, route, status in cursor.fetchall():
            key = (clean_value(name).lower(), clean_value(city).lower(), clean_value(route).lower())
            active_map[key] = (db_id, status)
            
        added_count = 0
        preserved_ids = set()
        today_str = datetime.date.today().isoformat()
        
        insert_sql = """
        INSERT INTO sponsors (organisation_name, town_city, county, rating, route, status, date_added, last_seen)
        VALUES (?, ?, ?, ?, ?, 'Active', ?, ?)
        """
        update_sql = """
        UPDATE sponsors SET last_seen = ?, status = ?, county = ?, rating = ? WHERE id = ?
        """
        
        inserts = []
        updates = []
        
        for row in reader:
            if not row or len(row) < 5:
                continue
            name = clean_value(row[0])
            city = clean_value(row[1])
            county = clean_value(row[2])
            rating = clean_value(row[3])
            route = clean_value(row[4])
            
            if not name:
                continue
                
            key = (name.lower(), city.lower(), route.lower())
            if key in active_map:
                db_id, status = active_map[key]
                updates.append((today_str, 'Active', county, rating, db_id))
                preserved_ids.add(db_id)
            else:
                inserts.append((name, city, county, rating, route, today_str, today_str))
                added_count += 1
                
        if inserts:
            cursor.executemany(insert_sql, inserts)
        if updates:
            cursor.executemany(update_sql, updates)
            
        # Set removed status
        removed_ids = []
        for key, (db_id, _) in active_map.items():
            if db_id not in preserved_ids:
                removed_ids.append((db_id,))
        
        removed_count = len(removed_ids)
        if removed_ids:
            cursor.executemany("UPDATE sponsors SET status = 'Removed' WHERE id = ?", removed_ids)
            
        cursor.execute("SELECT COUNT(*) FROM sponsors WHERE status != 'Removed'")
        total_sponsors = cursor.fetchone()[0]
        
        cursor.execute("""
        INSERT INTO sync_history (sync_date, csv_url, added_count, removed_count, total_sponsors)
        VALUES (?, ?, ?, ?, ?)
        """, (today_str, csv_url, added_count, removed_count, total_sponsors))
        
        conn.commit()
        conn.close()
        print(f"[Sync] Sponsor registry updated. Added: {added_count}, Removed: {removed_count}, Active sponsors: {total_sponsors}")
        return True
    except Exception as e:
        print(f"[Sync] GOV.UK crawl crashed: {e}")
        return False

def run_jobs_sync():
    """Loops over pre-seeded ATS board mappings and fetches fresh jobs."""
    db_init()
    print("[Sync] Executing daily job crawl for mapped sponsors...")
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT company_name, ats_type, ats_token FROM sponsor_ats_mappings")
    mappings = cursor.fetchall()
    conn.close()
    
    total_scraped = 0
    for company_name, ats_type, token in mappings:
        print(f"[Scraper] Scouting jobs for: {company_name} ({ats_type})")
        if ats_type == "greenhouse":
            count = crawl_greenhouse(company_name, token)
        elif ats_type == "lever":
            count = crawl_lever(company_name, token)
        else:
            count = 0
        total_scraped += count
        
    print(f"[Scraper] Sync completed. Crawled {total_scraped} active jobs across {len(mappings)} firms.")
    return True

def global_sync_daemon():
    """Runs daily backend sync pipelines."""
    # Execute immediately on start if database is completely dry
    db_init()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sponsors")
    count = cursor.fetchone()[0]
    conn.close()
    
    if count == 0:
        print("[Daemon] Core database is empty. Running initial sync sequence...")
        run_sponsors_sync()
        run_jobs_sync()
        
    while True:
        time.sleep(24 * 3600) # sync once a day
        print("[Daemon] Executing scheduled daily database synchronization...")
        try:
            run_sponsors_sync()
            run_jobs_sync()
        except Exception as e:
            print(f"[Daemon] Sync thread error: {e}")

# ---------------------------------------------------------------------------
# API ROUTER & CONTROLLER
# ---------------------------------------------------------------------------

class JobRadarHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass # Silence console noise
        
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/sync":
            print("[API] Manual database sync initiated.")
            success1 = run_sponsors_sync()
            success2 = run_jobs_sync()
            self.send_json({"status": "success" if (success1 and success2) else "failed"})
            
        elif parsed.path == "/api/crawl":
            # On-demand site crawler
            length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(length).decode('utf-8')
            params = json.loads(body) if body else {}
            
            sponsor_id = params.get("sponsor_id")
            if not sponsor_id:
                self.send_error(400, "Missing sponsor_id")
                return
                
            conn = sqlite3.connect(DB_FILE)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sponsors WHERE id = ?", (sponsor_id,))
            sponsor = cursor.fetchone()
            
            if not sponsor:
                conn.close()
                self.send_error(404, "Sponsor not found")
                return
                
            company_name = sponsor["organisation_name"]
            city = sponsor["town_city"]
            careers_url = sponsor["careers_url"]
            
            # Auto discover url if missing
            if not careers_url:
                print(f"[Crawler] Auto-discovering careers url for: {company_name}")
                careers_url = auto_discover_careers_url(company_name, city)
                if careers_url:
                    cursor.execute("UPDATE sponsors SET careers_url = ? WHERE id = ?", (careers_url, sponsor_id))
                    conn.commit()
            
            if not careers_url:
                conn.close()
                self.send_json({"status": "failed", "reason": "No careers page url found", "jobs": []})
                return
                
            # Perform web crawl
            print(f"[Crawler] Scraping custom webpage: {company_name} ({careers_url})")
            jobs_added = scrape_custom_website(company_name, careers_url, sponsor_id)
            
            # Fetch and return the newly crawled jobs
            cursor.execute("SELECT * FROM jobs WHERE sponsor_id = ? ORDER BY id DESC", (sponsor_id,))
            newly_jobs = [dict(r) for r in cursor.fetchall()]
            conn.close()
            
            self.send_json({
                "status": "success",
                "careers_url": careers_url,
                "jobs_added": jobs_added,
                "jobs": newly_jobs
            })
        else:
            self.send_error(404)
            
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        query = urllib.parse.parse_qs(parsed.query)
        
        if path.startswith("/api/"):
            self.handle_api(path, query)
        else:
            self.handle_static(path)
            
    def handle_static(self, path):
        # Route static UI content
        if path == "/" or path == "/index.html":
            file_path = "index.html"
            content_type = "text/html; charset=utf-8"
        elif path == "/style.css":
            file_path = "style.css"
            content_type = "text/css; charset=utf-8"
        elif path == "/app.js":
            file_path = "app.js"
            content_type = "application/javascript; charset=utf-8"
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b"Not Found")
            return
            
        if not os.path.exists(file_path):
            # Help local testing when run inside uksponsorjobs directory
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(f"/* File {file_path} is currently being created. Please refresh in a moment! */".encode('utf-8'))
            return
            
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.end_headers()
        with open(file_path, "rb") as f:
            self.wfile.write(f.read())
            
    def handle_api(self, path, query):
        conn = sqlite3.connect(DB_FILE)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        if path == "/api/jobs":
            # Search jobs
            q = query.get("q", [""])[0].strip()
            dept = query.get("dept", [""])[0].strip()
            city = query.get("city", [""])[0].strip()
            
            try:
                page = int(query.get("page", ["1"])[0])
            except ValueError:
                page = 1
            try:
                limit = int(query.get("limit", ["15"])[0])
            except ValueError:
                limit = 15
            limit = min(max(1, limit), 100)
            offset = (page - 1) * limit
            
            conditions = []
            params = []
            
            if q:
                conditions.append("(job_title LIKE ? OR company_name LIKE ? OR department LIKE ?)")
                params.extend([f"%{q}%", f"%{q}%", f"%{q}%"])
            if dept:
                conditions.append("department = ?")
                params.append(dept)
            if city:
                conditions.append("(location LIKE ? OR location = 'UK')")
                params.append(f"%{city}%")
                
            where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""
            
            # Total matches
            cursor.execute(f"SELECT COUNT(*) FROM jobs {where_clause}", params)
            total = cursor.fetchone()[0]
            
            # Fetch records
            cursor.execute(f"""
            SELECT * FROM jobs 
            {where_clause} 
            ORDER BY id DESC
            LIMIT ? OFFSET ?
            """, params + [limit, offset])
            rows = cursor.fetchall()
            
            jobs = [dict(r) for r in rows]
            self.send_json({
                "jobs": jobs,
                "meta": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "pages": math.ceil(total / limit) if total > 0 else 0
                }
            })
            
        elif path == "/api/jobs/filters":
            # Fetch distinct departments and cities to fill job search filters
            cursor.execute("SELECT DISTINCT department FROM jobs WHERE department != '' ORDER BY department ASC")
            departments = [r[0] for r in cursor.fetchall()]
            
            cursor.execute("""
            SELECT DISTINCT location FROM jobs 
            WHERE location != '' AND location != 'UK' AND location NOT LIKE '%united kingdom%'
            ORDER BY location ASC LIMIT 30
            """)
            locations = [r[0] for r in cursor.fetchall()]
            
            self.send_json({
                "departments": departments,
                "locations": locations
            })
            
        elif path == "/api/sponsors":
            # Direct sponsor registry lookup (Sponsors tab)
            q = query.get("q", [""])[0].strip()
            city = query.get("city", [""])[0].strip()
            
            try:
                page = int(query.get("page", ["1"])[0])
            except ValueError:
                page = 1
            limit = 20
            offset = (page - 1) * limit
            
            conditions = ["status != 'Removed'"]
            params = []
            
            if q:
                conditions.append("organisation_name LIKE ?")
                params.append(f"%{q}%")
            if city:
                conditions.append("town_city = ?")
                params.append(city)
                
            where_clause = " WHERE " + " AND ".join(conditions)
            
            cursor.execute(f"SELECT COUNT(*) FROM sponsors {where_clause}", params)
            total = cursor.fetchone()[0]
            
            cursor.execute(f"""
            SELECT * FROM sponsors 
            {where_clause} 
            ORDER BY organisation_name COLLATE NOCASE ASC
            LIMIT ? OFFSET ?
            """, params + [limit, offset])
            rows = cursor.fetchall()
            
            sponsors = [dict(r) for r in rows]
            self.send_json({
                "sponsors": sponsors,
                "meta": {
                    "total": total,
                    "page": page,
                    "limit": limit,
                    "pages": math.ceil(total / limit) if total > 0 else 0
                }
            })
            
        else:
            self.send_error(404, "API Endpoint Not Found")
            
        conn.close()
        
    def send_json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

def main():
    # Start the daily database sync background daemon
    daemon = threading.Thread(target=global_sync_daemon, daemon=True)
    daemon.start()
    
    # Run the TCP API server
    socketserver.TCPServer.allow_reuse_address = True
    with socketserver.TCPServer(("", PORT), JobRadarHandler) as httpd:
        print("==================================================")
        print("    UK SPONSORSHIP JOBS SERVER IS RUNNING (8000)   ")
        print("        Visit: http://localhost:8000/             ")
        print("==================================================")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nShutting down uksponsorjobs server...")

if __name__ == "__main__":
    main()
