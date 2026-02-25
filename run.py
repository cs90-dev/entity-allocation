#!/usr/bin/env python3
"""Runner script for ceviche CLI."""
import sys
import os

# Add repo root to path so 'ceviche' package is found
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ceviche.cli import main

if __name__ == "__main__":
    main()
