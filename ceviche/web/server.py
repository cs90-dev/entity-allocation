#!/usr/bin/env python3
"""Run the Entity Allocation web server."""
import os
import sys

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import uvicorn


def main():
    port = int(os.environ.get("PORT", 8000))
    print(f"\n  📊 Entity Allocation starting at http://localhost:{port}\n")
    uvicorn.run(
        "ceviche.web.api:app",
        host="0.0.0.0",
        port=port,
        reload=True,
        reload_dirs=[os.path.dirname(os.path.dirname(os.path.abspath(__file__)))],
    )


if __name__ == "__main__":
    main()
