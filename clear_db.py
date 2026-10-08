from dotenv import load_dotenv
import os
import psycopg2

load_dotenv()

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()

cur.execute("DELETE FROM jobs;")

conn.commit()
cur.close()
conn.close()

print("Table cleared!")