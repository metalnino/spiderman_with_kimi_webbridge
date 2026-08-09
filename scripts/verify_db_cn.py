import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from db import connect, ping

OUT = ROOT / "data" / "trial_multi" / "db_ping.json"


def main():
    info = ping()
    conn = connect()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO notices (source_id, source_name, external_id, title, city, content_hash) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE title=VALUES(title), city=VALUES(city)",
                ("smoke", "测试源", "cn-1", "绿植租摆中文测试", "南京", "smokehash000000000000000000000000000002"),
            )
            cur.execute(
                "SELECT id, title, city FROM notices WHERE external_id=%s",
                ("cn-1",),
            )
            row = cur.fetchone()
            cur.execute("DELETE FROM notices WHERE external_id=%s", ("cn-1",))
    finally:
        conn.close()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps({"ping": info, "cn_row": row}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("WROTE", OUT)


if __name__ == "__main__":
    main()
