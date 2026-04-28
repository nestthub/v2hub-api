#!/usr/bin/env python3
"""
Simple HTTP server for viewing documentation.
Run this script and open http://localhost:8080 in your browser.
"""

from functools import partial
from pathlib import Path
import http.server
import socketserver
import sys


docs_dir = Path(__file__).parent / "docs"
if not docs_dir.exists():
    print(f"Error: Documentation directory '{docs_dir}' not found!")
    sys.exit(1)

PORT = 8080


class CustomHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    """Custom handler with local-dev headers and cleaner logging."""

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
        super().end_headers()

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {format % args}")


class ReusableTCPServer(socketserver.TCPServer):
    allow_reuse_address = True


def main():
    print("=" * 70)
    print("VPN Subscription API - Documentation Server")
    print("=" * 70)
    print(f"\n📚 Serving documentation from: {docs_dir}")
    print(f"🌐 Open your browser and navigate to: http://localhost:{PORT}")
    print(f"\n💡 Press Ctrl+C to stop the server\n")
    print("=" * 70)

    handler = partial(CustomHTTPRequestHandler, directory=str(docs_dir))

    try:
        with ReusableTCPServer(("", PORT), handler) as httpd:
            httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n\n🛑 Server stopped by user")
        sys.exit(0)
    except OSError as e:
        if e.errno in (48, 98):
            print(f"\n❌ Error: Port {PORT} is already in use!")
            print("💡 Try a different port or stop the other service\n")
            sys.exit(1)
        raise


if __name__ == "__main__":
    main()
