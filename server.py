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

# Verified Premium Visa Sponsors ATS Board Mappings (tenant/token mappings)
PRESEED_ATS_MAPPINGS = [
    ("Lloyds Banking Group", "workday", "lbg", "LBG_Careers"),
    ("Barclays", "workday", "barclays", "Barclays_Careers"),
    ("PricewaterhouseCoopers", "workday", "pwc", "PwC_Careers"),
    ("Monzo Bank", "greenhouse", "monzo", "monzo"),
    ("Deliveroo", "greenhouse", "deliveroo", "deliveroo"),
    ("Revolut", "lever", "revolut", "revolut"),
    ("Wise", "greenhouse", "transferwise", "transferwise"),
    ("Starling Bank", "greenhouse", "starlingbank", "starlingbank"),
    ("Snyk", "greenhouse", "snyk", "snyk"),
    ("Checkout.com", "greenhouse", "checkout", "checkout"),
    ("Improbable", "greenhouse", "improbable", "improbable"),
    ("Skyscanner", "greenhouse", "skyscanner", "skyscanner"),
    ("Gousto", "greenhouse", "gousto", "gousto"),
    ("Gymshark", "greenhouse", "gymshark", "gymshark"),
    ("Curve", "greenhouse", "curve", "curve"),
    ("Cleo", "greenhouse", "cleo", "cleo"),
    ("Octopus Energy", "greenhouse", "octopusenergy", "octopusenergy"),
    ("DeepMind", "greenhouse", "deepmind", "deepmind"),
    ("Graphcore", "greenhouse", "graphcore", "graphcore"),
    ("TrueLayer", "greenhouse", "truelayer", "truelayer"),
    ("Zego", "greenhouse", "zego", "zego"),
    ("Marshmallow", "greenhouse", "marshmallow", "marshmallow"),
    ("Farewill", "greenhouse", "farewill", "farewill"),
    ("Bloom & Wild", "greenhouse", "bloomandwild", "bloomandwild"),
    ("Paddle", "greenhouse", "paddle", "paddle"),
    ("Motorway", "greenhouse", "motorway", "motorway"),
    ("Depop", "greenhouse", "depop", "depop"),
    ("Lyst", "greenhouse", "lyst", "lyst"),
    ("Trainline", "greenhouse", "trainline", "trainline"),
    ("Zilch", "greenhouse", "zilch", "zilch"),
    ("Thought Machine", "greenhouse", "thoughtmachine", "thoughtmachine"),
    ("PrimaryBid", "greenhouse", "primarybid", "primarybid"),
    ("Wayve", "greenhouse", "wayve", "wayve"),
    ("Synthesia", "greenhouse", "synthesia", "synthesia"),
    ("Onfido", "greenhouse", "onfido", "onfido"),
    ("ComplyAdvantage", "greenhouse", "complyadvantage", "complyadvantage"),
    ("Multiverse", "greenhouse", "multiverse", "multiverse"),
    ("Snowplow", "greenhouse", "snowplow", "snowplow"),
    ("Faculty", "greenhouse", "faculty", "faculty"),
    ("Signal AI", "greenhouse", "signalai", "signalai"),
    ("Healx", "greenhouse", "healx", "healx"),
    ("BrewDog", "greenhouse", "brewdog", "brewdog")
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
        ats_tenant TEXT,
        ats_token TEXT
    )
    """)
    
    # Indexes for ultra-fast query execution
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_name ON sponsors(organisation_name COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_city ON sponsors(town_city COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sponsors_status ON sponsors(status)")
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_title ON jobs(job_title COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_dept ON jobs(department COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_loc ON jobs(location COLLATE NOCASE)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_jobs_company ON jobs(company_name)")
    
    # Pre-seed premium mappings
    for name, ats_type, tenant, token in PRESEED_ATS_MAPPINGS:
        try:
            cursor.execute("""
            INSERT OR IGNORE INTO sponsor_ats_mappings (company_name, ats_type, ats_tenant, ats_token)
            VALUES (?, ?, ?, ?)
            """, (name, ats_type, tenant, token))
        except Exception:
            pass
            
    conn.commit()
    conn.close()

# ---------------------------------------------------------------------------
# AUTOMATED BRAND & CAREER URL DISCOVERY
# ---------------------------------------------------------------------------

def clean_company_name_for_suggest(name):
    """Strips complex corporate suffixes to yield perfect brand queries for autocomplete search."""
    name_clean = re.sub(r'\b(ltd|limited|plc|uk|co|group|holdings|services|bank|corporation|corp|llp|lp|assoc|intl|international)\b', '', name, flags=re.IGNORECASE)
    name_clean = re.sub(r'[^a-zA-Z0-9\s]', '', name_clean)
    name_clean = re.sub(r'\s+', ' ', name_clean).strip()
    
    words = name_clean.split()
    if words:
        if len(words[0]) <= 2 and len(words) > 1:
            return f"{words[0]} {words[1]}"
        return words[0]
    return name

def auto_discover_careers_url(company_name, city):
    """Autocomplete Resolver: searches Clearbit, extracts official domain, and probes careers path candidates."""
    query = clean_company_name_for_suggest(company_name)
    url = f"https://autocomplete.clearbit.com/v1/companies/suggest?query={urllib.parse.quote(query)}"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    
    domain = ""
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=6) as response:
            data = json.loads(response.read().decode('utf-8'))
        
        if data:
            for match in data:
                m_name = match.get("name", "").lower()
                m_domain = match.get("domain", "")
                if query.lower() in m_name and m_domain:
                    domain = m_domain
                    break
            if not domain:
                domain = data[0].get("domain", "")
    except Exception:
        pass
        
    if not domain:
        cleaned = query.lower().replace(" ", "")
        domain = f"{cleaned}.co.uk"
        
    candidates = [
        f"https://{domain}/careers",
        f"https://{domain}/jobs",
        f"https://{domain}/careers-at-{query.lower().replace(' ', '-')}",
        f"https://careers.{domain}",
        f"https://jobs.{domain}",
        f"https://{domain}/work-with-us",
        f"https://{domain}"
    ]
    
    for cand in candidates:
        try:
            req_probe = urllib.request.Request(cand, headers=headers)
            with urllib.request.urlopen(req_probe, timeout=3) as resp:
                if resp.status == 200:
                    return cand
        except Exception:
            continue
            
    return f"https://{domain}/careers"

# ---------------------------------------------------------------------------
# "SPONSOR WEB RADAR" MULTI-ATS CRAWLER (HYBRID JSON & HTML SPIDER)
# ---------------------------------------------------------------------------

def crawl_workday(company_name, tenant, board, sponsor_id=None):
    """Crawls active jobs directly from Workday JSON Search API, retrieving 100% of open vacancies."""
    base_url = f"https://{tenant}.wd3.myworkdayjobs.com/wday/cxs/{tenant}/{board}/jobs"
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
        'Origin': f'https://{tenant}.wd3.myworkdayjobs.com',
        'Referer': f'https://{tenant}.wd3.myworkdayjobs.com/{board}'
    }
    
    offset = 0
    limit = 20
    total = 1
    jobs_added = 0
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    today_str = datetime.date.today().isoformat()
    
    try:
        while offset < total and offset < 200: # safety cap at 200 jobs
            payload = json.dumps({
                "appliedFacets": {},
                "limit": limit,
                "offset": offset,
                "searchText": ""
            }).encode('utf-8')
            
            req = urllib.request.Request(base_url, data=payload, headers=headers, method='POST')
            with urllib.request.urlopen(req, timeout=12) as response:
                data = json.loads(response.read().decode('utf-8'))
                
            total = data.get("total", 0)
            job_postings = data.get("jobPostings", [])
            
            if not job_postings:
                break
                
            for item in job_postings:
                raw_id = f"workday-{tenant}-{item.get('bulletinNumber', item.get('workdayJobId', ''))}"
                title = clean_value(item.get("title", ""))
                
                ext_path = item.get("externalPath", "")
                job_url = f"https://{tenant}.wd3.myworkdayjobs.com/{board}{ext_path}"
                
                location = item.get("locationsText", "UK")
                if any(non_uk in location.lower() for non_uk in ["usa", "canada", "germany", "france", "india"]) and "united kingdom" not in location.lower() and "london" not in location.lower():
                    continue
                    
                cursor.execute("""
                INSERT OR REPLACE INTO jobs (sponsor_id, company_name, job_title, department, location, job_url, posted_date, source, raw_id)
                VALUES (?, ?, ?, 'Corporate', ?, ?, ?, 'Workday API', ?)
                """, (sponsor_id, company_name, title, location, job_url, today_str, raw_id))
                jobs_added += 1
                
            offset += limit
            time.sleep(0.35)
            
        conn.commit()
    except Exception as e:
        print(f"[Workday Scraper] Direct crawl failed for '{company_name}': {e}")
    finally:
        conn.close()
        
    return jobs_added

def crawl_greenhouse(company_name, token, sponsor_id=None):
    """Crawls active jobs from Greenhouse Board API."""
    url = f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    jobs_added = 0
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
        if "jobs" not in data:
            return 0
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        today_str = datetime.date.today().isoformat()
        for item in data["jobs"]:
            raw_id = f"greenhouse-{item['id']}"
            title = clean_value(item.get("title", ""))
            job_url = clean_value(item.get("absolute_url", ""))
            loc_data = item.get("location", {})
            location = loc_data.get("name", "UK") if loc_data else "UK"
            if any(non_uk in location.lower() for non_uk in ["usa", "canada", "germany", "france", "india"]) and "united kingdom" not in location.lower() and "london" not in location.lower():
                continue
            depts = item.get("departments", [])
            department = depts[0].get("name", "General") if depts else "General"
            
            cursor.execute("""
            INSERT OR REPLACE INTO jobs (sponsor_id, company_name, job_title, department, location, job_url, posted_date, source, raw_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Greenhouse API', ?)
            """, (sponsor_id, company_name, title, department, location, job_url, today_str, raw_id))
            jobs_added += 1
        conn.commit()
        conn.close()
    except Exception:
        pass
    return jobs_added

def crawl_lever(company_name, token, sponsor_id=None):
    """Crawls active jobs from Lever Posting API."""
    url = f"https://api.lever.co/v0/postings/{token}?group=team"
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    jobs_added = 0
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        today_str = datetime.date.today().isoformat()
        for group in data:
            dept_name = group.get("title", "General")
            postings = group.get("postings", [])
            for item in postings:
                raw_id = f"lever-{item['id']}"
                title = clean_value(item.get("title", ""))
                job_url = clean_value(item.get("hostedUrl", ""))
                categories = item.get("categories", {})
                location = categories.get("location", "UK")
                if any(non_uk in location.lower() for non_uk in ["usa", "us", "germany", "india"]) and "london" not in location.lower() and "united kingdom" not in location.lower():
                    continue
                cursor.execute("""
                INSERT OR REPLACE INTO jobs (sponsor_id, company_name, job_title, department, location, job_url, posted_date, source, raw_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'Lever API', ?)
                """, (sponsor_id, company_name, title, dept_name, location, job_url, today_str, raw_id))
                jobs_added += 1
        conn.commit()
        conn.close()
    except Exception:
        pass
    return jobs_added

def scrape_company_careers_page_smart(company_name, careers_url, sponsor_id=None):
    """Smart Hybrid Scraper: crawls company webpage directly, auto-detects ATS scripts embeds, and falls back to anchor link extraction."""
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36'}
    try:
        req = urllib.request.Request(careers_url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as response:
            html = response.read().decode('utf-8', errors='ignore')
            
        gh_matches = re.findall(r'grnh_board_token\s*=\s*[\'"]([a-zA-Z0-9_\-]+)[\'"]', html)
        if not gh_matches:
            gh_matches = re.findall(r'boards\.greenhouse\.io/(?:embed/job_board\?board_token=)?([a-zA-Z0-9_\-]+)', html)
            
        if gh_matches:
            token = gh_matches[0]
            jobs_added = crawl_greenhouse(company_name, token, sponsor_id)
            if jobs_added > 0:
                return jobs_added
                
        lever_matches = re.findall(r'jobs\.lever\.co/([a-zA-Z0-9_\-]+)', html)
        if lever_matches:
            token = lever_matches[0]
            jobs_added = crawl_lever(company_name, token, sponsor_id)
            if jobs_added > 0:
                return jobs_added
                
        wd_matches = re.findall(r'([a-zA-Z0-9_\-]+)\.wd3\.myworkdayjobs\.com/([a-zA-Z0-9_\-]+)', html)
        if wd_matches:
            tenant, board = wd_matches[0]
            jobs_added = crawl_workday(company_name, tenant, board, sponsor_id)
            if jobs_added > 0:
                return jobs_added
                
        parsed_base = urllib.parse.urlparse(careers_url)
        base_domain = f"{parsed_base.scheme}://{parsed_base.netloc}"
        
        anchors = re.findall(r'<a\s+[^>]*?href=["\']([^"\']+)["\'][^>]*?>(.*?)</a>', html, re.IGNORECASE | re.DOTALL)
        
        today_str = datetime.date.today().isoformat()
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        
        seen_urls = set()
        jobs_added = 0
        
        job_keywords = ["engineer", "developer", "designer", "manager", "nurse", "analyst", "operator", "consultant", "technician", 
                        "lead", "director", "writer", "architect", "support", "intern", "graduate", "specialist", "associate", 
                        "practitioner", "officer", "administrator", "head of", "recruiter", "executive"]
                        
        for href, text in anchors:
            text_clean = re.sub(r'<[^>]+>', '', text).strip()
            text_clean = re.sub(r'\s+', ' ', text_clean)
            
            href = href.strip()
            if not href or not text_clean:
                continue
                
            text_lower = text_clean.lower()
            href_lower = href.lower()
            
            is_job = False
            if 5 < len(text_clean) < 65:
                if any(kw in text_lower for kw in job_keywords):
                    is_job = True
                elif any(p in href_lower for p in ["/jobs/", "/careers/", "/vacancy/", "/openings/", "/apply/", "lever.co", "greenhouse.io"]):
                    if not any(noise in text_lower for noise in ["sign in", "login", "cookie", "privacy", "about us", "terms", "faq", "contact", "home", "search"]):
                        is_job = True
            
            if is_job:
                if any(noise in text_lower for noise in ["sign in", "login", "cookie", "privacy", "about us", "terms", "faq", "contact", "home", "careers", "jobs"]):
                    continue
                if href.startswith("#") or href.startswith("javascript:") or href.startswith("tel:") or href.startswith("mailto:"):
                    continue
                    
                if href.startswith("/"):
                    job_url = base_domain + href
                elif not href.startswith("http"):
                    job_url = careers_url.rstrip("/") + "/" + href
                else:
                    job_url = href
                    
                if job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                
                raw_hash = abs(hash(job_url))
                raw_id = f"spider-{company_name.lower().replace(' ', '-')}-{raw_hash}"
                
                cursor.execute("""
                INSERT OR REPLACE INTO jobs (sponsor_id, company_name, job_title, department, location, job_url, posted_date, source, raw_id)
                VALUES (?, ?, ?, 'Careers Portal', 'UK', ?, ?, 'Web Spider', ?)
                """, (sponsor_id, company_name, text_clean, job_url, today_str, raw_id))
                jobs_added += 1
                
        conn.commit()
        conn.close()
        return jobs_added
    except Exception:
        pass
    return 0

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
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            html = response.read().decode('utf-8')
        
        matches = re.findall(r'href="([^"]+?Worker_and_Temporary_Worker\.csv)"', html)
        if not matches:
            matches = re.findall(r'href="([^"]+?\.csv)"', html)
            
        if not matches:
            return False
            
        csv_url = matches[0]
        if csv_url.startswith('/'):
            csv_url = "https://www.gov.uk" + csv_url
            
        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM sync_history WHERE csv_url = ?", (csv_url,))
        synced = cursor.fetchone()
        
        cursor.execute("SELECT COUNT(*) FROM sponsors")
        total_in_db = cursor.fetchone()[0]
        
        if synced and total_in_db > 0:
            conn.close()
            return True
            
        print(f"[Sync] Downloading new sponsor register CSV...")
        csv_req = urllib.request.Request(csv_url, headers=headers)
        with urllib.request.urlopen(csv_req, timeout=60) as csv_resp:
            csv_data = csv_resp.read().decode('utf-8', errors='ignore')
            
        reader = csv.reader(csv_data.splitlines())
        try:
            next(reader)
        except StopIteration:
            conn.close()
            return False
            
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
        print(f"[Sync] GOV.UK sync completed. Sponsors count: {total_sponsors}")
        return True
    except Exception as e:
        print(f"[Sync] GOV.UK CSV sync crashed: {e}")
        return False

def auto_crawl_sponsor_batch():
    """Background Daemon Batch Scraper: Resolves career URLs and crawls jobs in efficient batches, supporting Workday, Greenhouse, and Lever JSON crawls."""
    db_init()
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    
    # 1. First, check if there are any pre-seeded ATS board mappings we haven't scraped yet
    cursor.execute("""
    SELECT m.company_name, m.ats_type, m.ats_tenant, m.ats_token, s.id 
    FROM sponsor_ats_mappings m
    LEFT JOIN sponsors s ON s.organisation_name LIKE '%' || m.company_name || '%' AND s.status != 'Removed'
    WHERE m.company_name NOT IN (SELECT DISTINCT company_name FROM jobs WHERE source IN ('Workday API', 'Greenhouse API', 'Lever API'))
    LIMIT 15
    """)
    ats_seeds = cursor.fetchall()
    
    if ats_seeds:
        print(f"[Crawler Batch] Found {len(ats_seeds)} pre-seeded high-yield ATS mappings to crawl...")
        total_seeded = 0
        for name, ats_type, tenant, token, sp_id in ats_seeds:
            print(f"[Crawler Batch] Direct JSON API Crawl: {name} ({ats_type})")
            if ats_type == "workday":
                count = crawl_workday(name, tenant, token, sp_id)
            elif ats_type == "greenhouse":
                count = crawl_greenhouse(name, token, sp_id)
            elif ats_type == "lever":
                count = crawl_lever(name, token, sp_id)
            else:
                count = 0
            total_seeded += count
            time.sleep(0.5)
        print(f"[Crawler Batch] Pre-seed API crawl complete! Indexed {total_seeded} vacancies.")
        conn.close()
        return total_seeded
        
    # 2. General Fallback: Fetch 40 sponsors without live vacancies, prioritizing popular cities
    cursor.execute("""
    SELECT id, organisation_name, town_city, careers_url 
    FROM sponsors 
    WHERE status != 'Removed' AND id NOT IN (SELECT DISTINCT sponsor_id FROM jobs WHERE sponsor_id IS NOT NULL)
    ORDER BY CASE 
        WHEN UPPER(town_city) IN ('LONDON', 'MANCHESTER', 'BIRMINGHAM', 'LEEDS', 'EDINBURGH', 'GLASGOW', 'BRISTOL', 'CAMBRIDGE', 'OXFORD') THEN 0
        ELSE 1 
    END ASC, id ASC
    LIMIT 40
    """)
    sponsors = cursor.fetchall()
    conn.close()
    
    if not sponsors:
        print("[Crawler Batch] All sponsors have been crawled or database is empty.")
        return 0
        
    print(f"[Crawler Batch] Starting background HTML crawl batch for {len(sponsors)} companies...")
    total_added = 0
    
    for sp_id, name, city, careers_url in sponsors:
        name_lower = name.lower()
        if any(noise in name_lower for noise in ["builders", "construction", "learning", "global", "tutorials"]):
            continue
            
        if not careers_url:
            careers_url = auto_discover_careers_url(name, city)
            if careers_url:
                conn = sqlite3.connect(DB_FILE)
                cursor = conn.cursor()
                cursor.execute("UPDATE sponsors SET careers_url = ? WHERE id = ?", (careers_url, sp_id))
                conn.commit()
                conn.close()
                
        if not careers_url:
            continue
            
        print(f"[Crawler Batch] Scouting HTML: {name} ({careers_url})")
        jobs_count = scrape_company_careers_page_smart(name, careers_url, sp_id)
        total_added += jobs_count
        time.sleep(0.5)
        
    print(f"[Crawler Batch] Batch completed! Crawled and indexed {total_added} live sponsorship roles.")
    return total_added

def global_sync_daemon():
    db_init()
    
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM sponsors")
    count = cursor.fetchone()[0]
    conn.close()
    
    if count == 0:
        print("[Daemon] Core database empty. Seeding official sponsors list...")
        run_sponsors_sync()
        
    while True:
        try:
            run_sponsors_sync()
            auto_crawl_sponsor_batch()
        except Exception as e:
            print(f"[Daemon] Error in background sync loop: {e}")
            
        time.sleep(300)

# ---------------------------------------------------------------------------
# API ROUTER & CONTROLLER
# ---------------------------------------------------------------------------

class JobRadarHandler(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass
        
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path == "/api/sync":
            print("[API] Manual database sync initiated.")
            success1 = run_sponsors_sync()
            success2 = auto_crawl_sponsor_batch()
            self.send_json({"status": "success" if (success1 or success2) else "failed"})
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
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.end_headers()
            self.wfile.write(f"/* Loading... */".encode('utf-8'))
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
            
            cursor.execute(f"SELECT COUNT(*) FROM jobs {where_clause}", params)
            total = cursor.fetchone()[0]
            
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
    daemon = threading.Thread(target=global_sync_daemon, daemon=True)
    daemon.start()
    
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
