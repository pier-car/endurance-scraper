"""Endurance Online scraper pipeline package.

A 3-phase ID-based pipeline:
    1. seed_ids       — discover horse IDs from elite rankings
    2. extract_pedigree — fetch anagrafica and recursively enqueue parents
    3. extract_performance — fetch race history per horse
"""

__all__ = ["common", "db", "endpoints"]
