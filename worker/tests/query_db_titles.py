import psycopg2

try:
    conn = psycopg2.connect("postgresql://postgres:postgres@localhost:5432/postgres")
    cur = conn.cursor()
    cur.execute("SELECT bookname, call_number FROM holdings h JOIN books b ON h.book_id=b.book_id WHERE h.library_code='111058' AND h.class_no LIKE '813.6%' LIMIT 5")
    for row in cur.fetchall():
        print(row)
        
    cur.execute("SELECT bookname, call_number FROM holdings h JOIN books b ON h.book_id=b.book_id WHERE h.library_code='111058' AND h.class_no LIKE '740%' LIMIT 5")
    for row in cur.fetchall():
        print(row)
    conn.close()
except Exception as e:
    print(e)
