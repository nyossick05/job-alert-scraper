from contextlib import asynccontextmanager
from fastapi import FastAPI
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import os
import psycopg2

from scraper import fetch_jobs, filter_jobs, save_jobs, notify_discord

load_dotenv()

scheduler = BackgroundScheduler()


def run_once():
    try:
        jobs = fetch_jobs()
        matches = filter_jobs(jobs)
        new_jobs = save_jobs(matches)
        print(f"Checked jobs: {len(matches)} matches, {len(new_jobs)} new")

        if new_jobs:
            notify_discord(new_jobs)
            print("Sent Discord notifications")
    except Exception as e:
        print(f"Scrape run failed: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    scheduler.add_job(run_once, "interval", hours=2)
    scheduler.start()
    yield
    scheduler.shutdown()


app = FastAPI(lifespan=lifespan)


@app.get("/")
def read_root():
    return {"message": "Hello from the job alert scraper!"}


@app.get("/jobs")
def get_jobs():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    cur = conn.cursor()

    cur.execute("""
        SELECT id, title, company, url, matched_keyword, date_found
        FROM jobs
        ORDER BY date_found DESC
        LIMIT 50
    """)
    rows = cur.fetchall()

    cur.close()
    conn.close()

    return [
        {
            "id": row[0],
            "title": row[1],
            "company": row[2],
            "url": row[3],
            "matched_keyword": row[4],
            "date_found": row[5],
        }
        for row in rows
    ]