"""升级并检查数据库，不重置任何已存在的数据。

运行：python scripts/migrate_database.py [--database /path/to/database.sqlite3]
首次从 v1 升级时自动将完整旧库备份到数据库所在目录的 backups/。
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT))
from app import create_app
from app.db import get_db


def main():
    parser = argparse.ArgumentParser(description="保留数据，将旧12表数据库迁移为16表结构")
    parser.add_argument("--database", type=Path, default=PROJECT / "instance" / "labreserve.sqlite3")
    args = parser.parse_args()
    app = create_app({"DATABASE": str(args.database.resolve())})
    with app.app_context():
        db = get_db()
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        schema = {}
        for name in names:
            schema[name] = {
                "count": db.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0],
                "columns": [dict(row) for row in db.execute(f'PRAGMA table_info("{name}")')],
                "foreign_keys": [dict(row) for row in db.execute(f'PRAGMA foreign_key_list("{name}")')],
                "indexes": [dict(row) for row in db.execute(f'PRAGMA index_list("{name}")')],
            }
        print(json.dumps({"database": str(args.database.resolve()), "user_version": db.execute("PRAGMA user_version").fetchone()[0], "table_count": len(names), "foreign_key_check": [list(row) for row in db.execute("PRAGMA foreign_key_check")], "schema": schema}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
