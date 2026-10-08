import time
from scraper import fetch_jobs, filter_jobs, save_jobs, notify_discord

INTERVAL_SECONDS = 60 * 30  # 30 minutes

def run_once():
    jobs = fetch_jobs()
    matches = filter_jobs(jobs)
    new_jobs = save_jobs(matches)

    print(f"Checked jobs — found {len(matches)} matches, {len(new_jobs)} new")

    if new_jobs:
        notify_discord(new_jobs)
        print("Sent Discord notifications")

if __name__ == "__main__":
    while True:
        run_once()
        print(f"Sleeping for {INTERVAL_SECONDS} seconds...")
        time.sleep(INTERVAL_SECONDS)