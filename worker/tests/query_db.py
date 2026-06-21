import psycopg2

try:
    conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/postgres")
    cur = conn.cursor()
    cur.execute("SELECT class_no, book_code, call_number FROM holdings WHERE library_code='111058' AND class_no LIKE '813.6%' LIMIT 10")
    for row in cur.fetchall():
        print(row)
    conn.close()
except Exception as e:
    print(e)
