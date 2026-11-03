"""Production server for the school network (Windows, Mac or Linux).

    python serve.py            -> http://<this-computer-ip>:8000
    set PORT=80 & python serve.py
Phones and iPads on the same Wi-Fi open the address that is printed below.
"""
import os
import socket

from server import create_app


def lan_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "127.0.0.1"


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    app = create_app()
    print("=" * 60)
    print(" Exam platform is running")
    print(f"   On this computer : http://localhost:{port}")
    print(f"   Phones / iPads   : http://{lan_ip()}:{port}")
    print("=" * 60)
    try:
        from waitress import serve

        serve(app, host="0.0.0.0", port=port, threads=16)
    except ImportError:
        app.run(host="0.0.0.0", port=port)
