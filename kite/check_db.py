import sqlite3
conn = sqlite3.connect('data/zerodha_data.db')
cursor = conn.cursor()
cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [t[0] for t in cursor.fetchall()]
print("Tables:", tables)

for table in tables[:3]:
    cursor.execute(f"SELECT * FROM {table} LIMIT 2")
    print(f"\n{table}:")
    for row in cursor.fetchall():
        print(row)
