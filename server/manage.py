"""Command line helpers.

  python -m server.manage create-admin <username> <password> [name]
  python -m server.manage set-password <username> <password>
  python -m server.manage backup
"""
import sys

from werkzeug.security import generate_password_hash

from . import create_app
from .db import get_db
from .utils import now


def main(argv):
    if not argv:
        print(__doc__)
        return 1
    app = create_app()
    with app.app_context():
        db = get_db()
        cmd = argv[0]
        if cmd == "create-admin" and len(argv) >= 3:
            name = argv[3] if len(argv) > 3 else "Principal"
            db.execute(
                "INSERT INTO users(name, username, password_hash, role, created_at) VALUES(?,?,?,'admin',?)",
                (name, argv[1], generate_password_hash(argv[2]), now()),
            )
            db.commit()
            print("Admin created:", argv[1])
        elif cmd == "set-password" and len(argv) == 3:
            cur = db.execute("UPDATE users SET password_hash=?, active=1, auth_version=auth_version+1 WHERE username=?", (generate_password_hash(argv[2]), argv[1]))
            db.commit()
            print("Updated" if cur.rowcount else "No such user")
        elif cmd == "backup":
            from .backup import create_backup

            print("Backup:", create_backup("manual", app))
        else:
            print(__doc__)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
