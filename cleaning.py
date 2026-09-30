"""
v1's text cleaning, moved out of clean.py so the daily job applies exactly the same rules.
clean.py (full rebuild) and daily_ingest.py (incremental) both import from here.
"""
import re
from config import MIN_WORDS


def clean(t):
    t = re.sub(r'(.)\1{2,}', r'\1\1', t)     # sirrrrr -> sirr, goooood -> good
    t = re.sub(r'([!?.,])\1+', r'\1', t)     # !!!!! -> !
    return re.sub(r'\s+', ' ', t).strip()


def is_substantive(t):
    """t must already be cleaned."""
    return len(t.split()) >= MIN_WORDS


def dedupe_key(t):
    """Two cleaned reviews with the same key are the same text."""
    return t.lower()
