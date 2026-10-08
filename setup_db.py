from dotenv import load_dotenv
import os
import psycopg2

load_dotenv()

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

cur.execute("""
    CREATE TABLE IF NOT EXISTS jobs (
        id SERIAL PRIMARY KEY,
        title TEXT NOT NULL,
        company TEXT,
        url TEXT UNIQUE NOT NULL,
        matched_keyword TEXT,
        date_found TIMESTAMP DEFAULT NOW()
    );
""")

conn.commit()
cur.close()
conn.close()

print("Table created successfully!")