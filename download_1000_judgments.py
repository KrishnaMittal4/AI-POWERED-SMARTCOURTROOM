"""
Download 1000 Indian Supreme Court Judgment PDFs
=================================================
Downloads real English-language Supreme Court judgment PDFs from the
PUBLIC, CC-BY-4.0 licensed AWS Open Data dataset:
  https://registry.opendata.aws/indian-supreme-court-judgments/

This script spreads the 1000 downloads across multiple years so you get
a diverse, representative corpus — useful for RAG evaluation and training.

Requirements:
    pip install boto3

Usage:
    # Test with a small batch first:
    python download_1000_judgments.py --count 10 --out data/pdfs --test

    # Full 1000-judgment run:
    python download_1000_judgments.py --count 1000 --out data/pdfs

    # Resume an interrupted run (skips already-downloaded files):
    python download_1000_judgments.py --count 1000 --out data/pdfs

    # Custom year range:
    python download_1000_judgments.py --count 1000 --out data/pdfs --start-year 2010 --end-year 2023
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime

# -- guard: require boto3 early so the error is readable
try:
    import boto3
    from botocore import UNSIGNED
    from botocore.config import Config
    from botocore.exceptions import ClientError, EndpointConnectionError, ReadTimeoutError
except ImportError:
    sys.exit(
        "\n[ERROR] boto3 is not installed.\n"
        "Run:  pip install boto3\n"
        "Then re-run this script.\n"
    )

# -- constants
BUCKET = "indian-supreme-court-judgments"
MIN_VALID_PDF_BYTES = 2_000   # real judgment PDFs are never this small
MAX_RETRIES = 3
DELAY_BETWEEN_FILES = 0.3     # seconds -- be polite to the public S3 bucket

# Year distribution: older years tend to have fewer files, recent ones more.
# Weighted towards 2015-2023 where the dataset is richest.
DEFAULT_YEAR_WEIGHTS = {
    2000: 30, 2001: 30, 2002: 30, 2003: 30, 2004: 30,
    2005: 40, 2006: 40, 2007: 40, 2008: 40, 2009: 40,
    2010: 50, 2011: 50, 2012: 50, 2013: 50, 2014: 50,
    2015: 60, 2016: 60, 2017: 60, 2018: 60, 2019: 60,
    2020: 70, 2021: 70, 2022: 70, 2023: 70,
}


def make_client():
    """S3 client with no credentials needed -- this bucket is public-read."""
    return boto3.client(
        "s3",
        config=Config(
            signature_version=UNSIGNED,
            retries={"max_attempts": MAX_RETRIES, "mode": "standard"},
            connect_timeout=30,
            read_timeout=120,
        ),
        region_name="ap-south-1",
    )


def list_pdf_keys(client, year: int, limit: int) -> list:
    """List up to `limit` English PDF keys for a given year."""
    prefix = f"data/pdf/year={year}/english/"
    keys = []
    try:
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=BUCKET, Prefix=prefix):
            for obj in page.get("Contents", []):
                if obj["Key"].lower().endswith(".pdf"):
                    keys.append(obj["Key"])
                    if len(keys) >= limit:
                        return keys
    except (ClientError, EndpointConnectionError, ReadTimeoutError) as e:
        print(f"  [WARNING] Could not list year={year}: {e}")
        return []
    return keys


def metadata_key_for(pdf_key: str, year: int) -> str:
    case_id = os.path.splitext(os.path.basename(pdf_key))[0]
    return f"metadata/json/year={year}/{case_id}.json"


def fetch_metadata(client, pdf_key: str, year: int, verbose: bool) -> dict:
    """Fetch case metadata -- never raises; falls back to {} on any error."""
    meta_key = metadata_key_for(pdf_key, year)
    for attempt in range(MAX_RETRIES):
        try:
            obj = client.get_object(Bucket=BUCKET, Key=meta_key)
            meta = json.loads(obj["Body"].read())
            if verbose:
                print(f"    [meta] {meta_key}\n{json.dumps(meta, indent=2)[:400]}")
            return meta
        except (ClientError, json.JSONDecodeError) as e:
            if attempt == MAX_RETRIES - 1:
                print(f"    [meta-warn] No usable metadata for {meta_key} ({e})")
                return {}
            time.sleep(0.5 * (attempt + 1))
    return {}


def safe_filename_from_metadata(meta: dict, case_id: str, year: int) -> str:
    """Build a clean, safe filename from official metadata."""
    parties = (meta.get("parties") or meta.get("title") or "").strip()
    looks_like_case_name = (
        8 <= len(parties) <= 200
        and any(sep in f" {parties.lower()} " for sep in [" v ", " vs ", " v. "])
    )
    if not looks_like_case_name:
        return f"{year}_{case_id}.pdf"

    clean = "".join(c if c.isalnum() or c in " _-" else "" for c in parties)
    clean = "_".join(clean.split())[:100]
    if not clean:
        return f"{year}_{case_id}.pdf"

    date = (meta.get("date") or meta.get("order_date") or "").strip()
    if date:
        clean += f"_{date.replace('-', '_').replace('/', '_')}"
    return f"{clean}.pdf"


def unique_path(out_dir: str, filename: str, used_names: set) -> str:
    """Ensure the filename is unique -- prevents silent overwrites."""
    base, ext = os.path.splitext(filename)
    candidate = filename
    n = 2
    while candidate in used_names or os.path.exists(os.path.join(out_dir, candidate)):
        candidate = f"{base}_dup{n}{ext}"
        n += 1
    used_names.add(candidate)
    return candidate


def download_one_pdf(client, pdf_key: str, out_path: str) -> bool:
    """Download with retries + integrity check. Removes partial files on failure.

    On Windows, antivirus/Defender can briefly lock the temp file that
    s3transfer writes before renaming it to the final path, causing a
    PermissionError (WinError 32). We catch OSError broadly and retry
    with a short sleep to let the AV scan finish.
    """
    for attempt in range(MAX_RETRIES):
        try:
            client.download_file(BUCKET, pdf_key, out_path)
        except PermissionError as e:
            # Windows: AV/Defender locked the temp file mid-rename.
            # Clean up any stray temp files boto3/s3transfer left behind.
            for tmp in [f for f in os.listdir(os.path.dirname(out_path) or ".")
                        if f.startswith(os.path.basename(out_path))]:
                try:
                    os.remove(os.path.join(os.path.dirname(out_path) or ".", tmp))
                except OSError:
                    pass
            if attempt == MAX_RETRIES - 1:
                print(f"    FAILED (PermissionError after {MAX_RETRIES} attempts): {e}")
                return False
            wait = 2.0 * (attempt + 1)
            print(f"    PermissionError (antivirus scan?) -- retrying in {wait:.0f}s ...")
            time.sleep(wait)
            continue
        except (ClientError, EndpointConnectionError, ReadTimeoutError) as e:
            if attempt == MAX_RETRIES - 1:
                print(f"    FAILED after {MAX_RETRIES} attempts: {e}")
                if os.path.exists(out_path):
                    os.remove(out_path)
                return False
            time.sleep(1.5 * (attempt + 1))
            continue

        size = os.path.getsize(out_path) if os.path.exists(out_path) else 0
        if size < MIN_VALID_PDF_BYTES:
            print(f"    WARN: too small ({size} bytes) -- removing")
            os.remove(out_path)
            return False
        with open(out_path, "rb") as f:
            header = f.read(5)
        if header != b"%PDF-":
            print(f"    WARN: not a valid PDF (header={header!r}) -- removing")
            os.remove(out_path)
            return False
        return True
    return False


def allocate_counts_by_year(total: int, start_year: int, end_year: int) -> dict:
    """Distribute `total` downloads across years proportional to DEFAULT_YEAR_WEIGHTS."""
    years = [y for y in DEFAULT_YEAR_WEIGHTS if start_year <= y <= end_year]
    if not years:
        years = list(range(start_year, end_year + 1))

    weights = {y: DEFAULT_YEAR_WEIGHTS.get(y, 40) for y in years}
    total_weight = sum(weights.values())
    allocation = {}
    assigned = 0

    for i, year in enumerate(years):
        if i == len(years) - 1:
            allocation[year] = total - assigned
        else:
            allocation[year] = max(1, round(total * weights[year] / total_weight))
            assigned += allocation[year]

    return allocation


def progress_bar(current: int, total: int, width: int = 40) -> str:
    pct = current / max(total, 1)
    filled = int(width * pct)
    bar = "#" * filled + "-" * (width - filled)
    return f"[{bar}] {current}/{total} ({pct*100:.1f}%)"


def run(total: int, out_dir: str, start_year: int, end_year: int, verbose: bool, test: bool):
    os.makedirs(out_dir, exist_ok=True)
    client = make_client()

    if test:
        print("\n" + "=" * 60)
        print("  TEST MODE -- downloading a small sample only")
        print("=" * 60)
        total = min(total, 10)

    allocation = allocate_counts_by_year(total, start_year, end_year)
    used_names = set(os.listdir(out_dir))

    manifest_path = os.path.join(out_dir, "manifest.json")
    manifest = []
    if os.path.exists(manifest_path):
        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
            print(f"Resuming: {len(manifest)} files already in manifest.")
        except (json.JSONDecodeError, OSError):
            pass

    # Build a fast-lookup set of already-downloaded source keys.
    # This is the primary dedup guard -- source_key is globally unique
    # per case in the dataset, so checking it avoids re-downloading a
    # case even if the filename on disk would be different.
    downloaded_keys: set = {m["source_key"] for m in manifest if "source_key" in m}

    print(f"\nTarget: {total} judgments across {len(allocation)} years")
    print(f"Output: {os.path.abspath(out_dir)}\n")
    print("Year allocation:")
    for year, count in sorted(allocation.items()):
        print(f"  {year}: {count} files")
    print()

    global_succeeded = 0
    global_failed = 0
    global_skipped = 0
    start_time = datetime.now()

    for year, year_count in sorted(allocation.items()):
        if year_count <= 0:
            continue

        print(f"\n{'=' * 60}")
        print(f"  Year {year}: targeting {year_count} files")
        print(f"{'=' * 60}")

        print(f"  Listing available PDFs for {year}...")
        pdf_keys = list_pdf_keys(client, year, limit=year_count)
        print(f"  Found {len(pdf_keys)} candidates.\n")

        if not pdf_keys:
            print(f"  [SKIP] No PDFs found for {year}.")
            continue

        year_ok = 0
        year_fail = 0

        for i, pdf_key in enumerate(pdf_keys, start=1):
            case_id = os.path.splitext(os.path.basename(pdf_key))[0]
            global_so_far = global_succeeded + global_failed + global_skipped + i - 1
            print(f"  {progress_bar(global_so_far, total)}  [{year} {i}/{len(pdf_keys)}] {case_id}")

            # -- Primary dedup: check source_key against manifest --------
            if pdf_key in downloaded_keys:
                print(f"    -> already downloaded (manifest), skipping")
                global_skipped += 1
                used_names.add(safe_filename_from_metadata({}, case_id, year))  # keep used_names consistent
                continue

            meta = fetch_metadata(client, pdf_key, year, verbose)
            filename = safe_filename_from_metadata(meta, case_id, year)

            # -- Secondary dedup: check if base file already on disk -----
            base_out_path = os.path.join(out_dir, filename)
            if os.path.exists(base_out_path):
                print(f"    -> file exists on disk, skipping")
                used_names.add(filename)
                global_skipped += 1
                continue

            # Only call unique_path if we're actually going to download.
            filename = unique_path(out_dir, filename, used_names)
            out_path = os.path.join(out_dir, filename)

            ok = download_one_pdf(client, pdf_key, out_path)
            if ok:
                year_ok += 1
                global_succeeded += 1
                size_kb = os.path.getsize(out_path) // 1024
                print(f"    OK -> {filename}  ({size_kb} KB)")
                manifest.append({
                    "filename": filename,
                    "source_key": pdf_key,
                    "year": year,
                    "case_name": meta.get("parties") or meta.get("title"),
                    "date": meta.get("date") or meta.get("order_date"),
                    "court": meta.get("court", "Supreme Court of India"),
                    "fallback_id": filename.startswith(f"{year}_{case_id}"),
                })
                # Save manifest after every success (crash-safe resume)
                with open(manifest_path, "w", encoding="utf-8") as f:
                    json.dump(manifest, f, indent=2, ensure_ascii=False)
            else:
                year_fail += 1
                global_failed += 1

            time.sleep(DELAY_BETWEEN_FILES)

        print(f"\n  Year {year} done: {year_ok} downloaded, {year_fail} failed.")

    elapsed = int((datetime.now() - start_time).total_seconds())
    mins, secs = divmod(elapsed, 60)

    print(f"\n{'=' * 60}")
    print(f"  COMPLETE!")
    print(f"  Downloaded : {global_succeeded}")
    print(f"  Skipped    : {global_skipped}  (already existed)")
    print(f"  Failed     : {global_failed}")
    print(f"  Time taken : {mins}m {secs}s")
    print(f"  Saved to   : {os.path.abspath(out_dir)}")
    print(f"  Manifest   : {manifest_path}")
    print(f"{'=' * 60}")
    print(f"\nNEXT STEPS:")
    print(f"  1. Verify a few PDFs in {out_dir}/")
    print(f"  2. Run:  python rag_pipeline.py   (to re-index)")
    print(f"  3. Restart your uvicorn server")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Download Indian Supreme Court judgment PDFs from AWS Open Data"
    )
    parser.add_argument("--count", type=int, default=1000,
                        help="Total PDFs to download (default: 1000)")
    parser.add_argument("--out", type=str, default=os.path.join("data", "pdfs"),
                        help="Output directory (default: data/pdfs)")
    parser.add_argument("--start-year", type=int, default=2000,
                        help="Earliest year to pull from (default: 2000)")
    parser.add_argument("--end-year", type=int, default=2023,
                        help="Latest year to pull from (default: 2023)")
    parser.add_argument("--test", action="store_true",
                        help="Test mode: download only 10 files")
    parser.add_argument("--verbose", action="store_true",
                        help="Print raw metadata JSON for debugging")
    args = parser.parse_args()

    run(
        total=args.count,
        out_dir=args.out,
        start_year=args.start_year,
        end_year=args.end_year,
        verbose=args.verbose,
        test=args.test,
    )
