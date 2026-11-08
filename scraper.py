import os
import re
import time
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

# Words that make a job "CS-related" (checked against title + description)
KEYWORDS = [
    "software", "developer", "development", "engineer", "engineering",
    "python", "java", "javascript", "backend", "frontend", "full stack",
    "web", "data", "machine learning", "cybersecurity", "security",
    "cloud", "devops", "computer", "computer science",
    "information technology", "ai",
]

# Where you want to work
SEARCH_LOCATION = "Washington, DC"
SEARCH_DISTANCE_KM = 50      # Adzuna uses kilometers
USAJOBS_RADIUS_MILES = 30    # USAJobs uses miles
USAJOBS_SEARCH_TERMS = ["intern", "student trainee", "pathways"]

# Word-boundary patterns, so "intern" doesn't match "internal"
INTERN_PATTERN = re.compile(
    r"\b(intern|interns|internship|internships|co-op|student trainee|pathways)\b"
)
KEYWORD_PATTERN = re.compile(
    r"\b(" + "|".join(re.escape(k) for k in KEYWORDS) + r")\b"
)
US_PATTERN = re.compile(r"\b(usa|us|united states)\b")

# Tag name -> pattern that triggers it
TAG_PATTERNS = {
    "clearance": re.compile(
        r"\bclearance\b|top secret|ts/sci|public trust", re.IGNORECASE
    ),
    "US citizenship": re.compile(
        r"\b(u\.?s\.?|united states) citizen", re.IGNORECASE
    ),
    "paid": re.compile(r"\bpaid\b|\bstipend\b|\$\s?\d", re.IGNORECASE),
    "unpaid": re.compile(r"\bunpaid\b", re.IGNORECASE),
    "remote": re.compile(r"\bremote\b", re.IGNORECASE),
    "hybrid": re.compile(r"\bhybrid\b", re.IGNORECASE),
}


def extract_tags(text):
    return [tag for tag, pattern in TAG_PATTERNS.items() if pattern.search(text)]


def is_us_job(job):
    location = (job.get("location") or "").lower()
    return bool(US_PATTERN.search(location))


def fetch_remoteok():
    response = requests.get(
        "https://remoteok.com/api",
        headers={"User-Agent": "Mozilla/5.0"},
        timeout=30,
    )
    response.raise_for_status()
    raw_jobs = response.json()[1:]  # first item is metadata, not a job

    jobs = []
    for job in raw_jobs:
        if not is_us_job(job):
            continue
        jobs.append({
            "title": job.get("position") or "",
            "company": job.get("company"),
            "url": job.get("url"),
            "location": job.get("location") or "Remote",
            "description": job.get("description") or "",
            "source": "remoteok",
            "prefiltered": False,
        })
    return jobs


def fetch_adzuna():
    app_id = os.getenv("ADZUNA_APP_ID")
    app_key = os.getenv("ADZUNA_APP_KEY")
    if not app_id or not app_key:
        print("Adzuna keys missing, skipping Adzuna")
        return []

    params = {
        "app_id": app_id,
        "app_key": app_key,
        "what_or": "intern internship",
        "category": "it-jobs",
        "where": SEARCH_LOCATION,
        "distance": SEARCH_DISTANCE_KM,
        "results_per_page": 50,
        "sort_by": "date",
    }
    response = requests.get(
        "https://api.adzuna.com/v1/api/jobs/us/search/1",
        params=params,
        timeout=30,
    )
    response.raise_for_status()

    jobs = []
    for job in response.json().get("results", []):
        jobs.append({
            "title": re.sub(r"<.*?>", "", job.get("title") or ""),
            "company": (job.get("company") or {}).get("display_name"),
            "url": job.get("redirect_url"),
            "location": (job.get("location") or {}).get("display_name"),
            "description": job.get("description") or "",
            "source": "adzuna",
            "prefiltered": True,
        })
    return jobs


def fetch_usajobs():
    api_key = os.getenv("USAJOBS_API_KEY")
    email = os.getenv("USAJOBS_EMAIL")
    if not api_key or not email:
        print("USAJobs keys missing, skipping USAJobs")
        return []

    headers = {
        "User-Agent": email,
        "Authorization-Key": api_key,
    }

    jobs = []
    for search_term in USAJOBS_SEARCH_TERMS:
        params = {
            "Keyword": search_term,
            "LocationName": SEARCH_LOCATION,
            "Radius": USAJOBS_RADIUS_MILES,
            "ResultsPerPage": 50,
        }
        response = requests.get(
            "https://data.usajobs.gov/api/search",
            headers=headers,
            params=params,
            timeout=30,
        )
        response.raise_for_status()

        items = response.json().get("SearchResult", {}).get("SearchResultItems", [])
        for item in items:
            posting = item.get("MatchedObjectDescriptor") or {}
            details = (posting.get("UserArea") or {}).get("Details") or {}
            jobs.append({
                "title": posting.get("PositionTitle") or "",
                "company": posting.get("OrganizationName"),
                "url": posting.get("PositionURI"),
                "location": posting.get("PositionLocationDisplay"),
                "description": details.get("JobSummary") or posting.get("QualificationSummary") or "",
                "source": "usajobs",
                "prefiltered": False,
            })
    return jobs


def fetch_jobs():
    all_jobs = []
    for source in (fetch_remoteok, fetch_adzuna, fetch_usajobs):
        try:
            found = source()
            print(f"{source.__name__}: fetched {len(found)} jobs")
            all_jobs.extend(found)
        except Exception as e:
            print(f"{source.__name__} failed: {e}")
    return all_jobs


def filter_jobs(jobs):
    matches = []
    for job in jobs:
        if not job["url"]:
            continue

        title = job["title"].lower()
        description = job["description"].lower()

        # Check 1: is it an internship? (title only)
        if not INTERN_PATTERN.search(title):
            continue

        # Check 2: is it CS-related?
        found = KEYWORD_PATTERN.search(title + " " + description)
        if found:
            matched = found.group(1)
        elif job["prefiltered"]:
            matched = "IT category match"
        else:
            continue

        matches.append({
            "title": job["title"],
            "company": job["company"],
            "url": job["url"],
            "location": job["location"],
            "source": job["source"],
            "matched_keyword": matched,
            "tags": extract_tags(job["title"] + " " + job["description"]),
        })
    return matches


def save_jobs(matches):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()

    new_jobs = []
    for job in matches:
        cur.execute("""
            INSERT INTO jobs (title, company, url, matched_keyword, location, source, tags)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
        """, (
            job["title"], job["company"], job["url"], job["matched_keyword"],
            job["location"], job["source"], job["tags"],
        ))

        if cur.rowcount > 0:
            new_jobs.append(job)

    conn.commit()
    cur.close()
    conn.close()
    return new_jobs


def notify_discord(new_jobs):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    for job in new_jobs:
        parts = [
            f"**New internship match!** {job['title']} at {job['company']}",
            f"{job['location']} ({job['source']})",
        ]
        if job["tags"]:
            parts.append("🏷 " + " · ".join(job["tags"]))
        parts.append(job["url"])

        requests.post(webhook_url, json={"content": "\n".join(parts)})
        time.sleep(1)  # Discord rate-limits rapid-fire webhook posts


if __name__ == "__main__":
    jobs = fetch_jobs()
    matches = filter_jobs(jobs)
    print(f"Found {len(matches)} matching jobs")

    new_jobs = save_jobs(matches)
    print(f"Inserted {len(new_jobs)} new jobs")

    if new_jobs:
        notify_discord(new_jobs)
        print("Sent Discord notifications")
    else:
        print("Nothing new to notify about")