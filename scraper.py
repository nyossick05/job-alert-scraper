import os
import re
import time
import requests
import psycopg2
from dotenv import load_dotenv

load_dotenv()

KEYWORDS = ["python", "backend", "django", "flask", "fastapi"]

# Change these to where YOU want to work (a city, state, or zip all work)
SEARCH_LOCATION = "Virginia"
SEARCH_DISTANCE_KM = 80

US_PATTERN = re.compile(r"\b(usa|us|united states)\b")


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
        "what_or": " ".join(KEYWORDS),
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
            "prefiltered": True,
        })
    return jobs


def fetch_jobs():
    all_jobs = []
    for source in (fetch_remoteok, fetch_adzuna):
        try:
            all_jobs.extend(source())
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

        matched = None
        for keyword in KEYWORDS:
            if keyword in title or keyword in description:
                matched = keyword
                break

        if matched is None and job["prefiltered"]:
            matched = "search match"
        if matched is None:
            continue

        matches.append({
            "title": job["title"],
            "company": job["company"],
            "url": job["url"],
            "location": job["location"],
            "matched_keyword": matched,
        })
    return matches


def save_jobs(matches):
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()

    new_jobs = []
    for job in matches:
        cur.execute("""
            INSERT INTO jobs (title, company, url, matched_keyword)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (url) DO NOTHING
        """, (job["title"], job["company"], job["url"], job["matched_keyword"]))

        if cur.rowcount > 0:
            new_jobs.append(job)

    conn.commit()
    cur.close()
    conn.close()
    return new_jobs


def notify_discord(new_jobs):
    webhook_url = os.getenv("DISCORD_WEBHOOK_URL")

    for job in new_jobs:
        message = {
            "content": (
                f"**New job match!** {job['title']} at {job['company']}\n"
                f"{job['location']}\n{job['url']}"
            )
        }
        requests.post(webhook_url, json=message)
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