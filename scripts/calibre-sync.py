#!/usr/bin/env python3
"""
Calibre to OwnBook Synchronization Bridge
Syncs ebooks (EPUB, PDF, MOBI) from a Calibre library directory (with metadata.db)
into an OwnBook instance via its PocketBase REST API.
"""

import os
import sys
import time
import sqlite3
import logging
from pathlib import Path
import urllib.request
import urllib.parse
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("calibre-ownbook-sync")

OWNBOOK_URL = os.environ.get("OWNBOOK_URL", "http://127.0.0.1:18093").rstrip("/")
OWNBOOK_USER = os.environ.get("OWNBOOK_USER", os.environ.get("APP_USER_EMAIL", "demo@e.co"))
OWNBOOK_PASSWORD = os.environ.get("OWNBOOK_PASSWORD", os.environ.get("APP_USER_PASSWORD", "demo1234"))
CALIBRE_PATH = os.environ.get("CALIBRE_LIBRARY_PATH", "/calibre_library")
SYNC_INTERVAL = int(os.environ.get("SYNC_INTERVAL_SECONDS", "300"))
MAX_UPLOAD_SIZE = int(os.environ.get("MAX_UPLOAD_SIZE_MB", "100")) * 1024 * 1024


def authenticate_ownbook(base_url, user, password):
    """Authenticate with PocketBase and return (auth_token, user_id)."""
    url = f"{base_url}/api/collections/users/auth-with-password"
    data = json.dumps({"identity": user, "password": password}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            return body.get("token"), body.get("record", {}).get("id")
    except Exception as e:
        logger.error(f"Failed to authenticate with OwnBook at {url}: {e}")
        return None, None


def get_existing_books(base_url, token):
    """Fetch existing book titles/ids from OwnBook."""
    url = f"{base_url}/api/collections/books/records?perPage=500"
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            items = body.get("items", [])
            # Map normalized title to book record
            return {item.get("title", "").strip().lower(): item for item in items}
    except Exception as e:
        logger.error(f"Failed to fetch existing books: {e}")
        return {}


def upload_book(base_url, token, user_id, title, author, description, file_path):
    """Upload a book file to PocketBase via multipart/form-data."""
    boundary = f"----WebKitFormBoundary{os.urandom(16).hex()}"
    filename = Path(file_path).name
    ext = Path(file_path).suffix.lower()

    content_type = "application/pdf" if ext == ".pdf" else "application/epub+zip"
    if ext == ".mobi":
        content_type = "application/x-mobipocket-ebook"

    try:
        with open(file_path, "rb") as f:
            file_bytes = f.read()
    except Exception as e:
        logger.error(f"Cannot read file {file_path}: {e}")
        return False

    if len(file_bytes) > MAX_UPLOAD_SIZE:
        logger.warning(f"Skipping {filename}: file size ({len(file_bytes)/(1024*1024):.1f}MB) exceeds limit")
        return False

    body = bytearray()
    fields = {
        "user": user_id,
        "title": title,
        "author": author or "Unknown",
        "parse_status": "pending"
    }
    if description:
        fields["description"] = description[:15000]

    for k, v in fields.items():
        body.extend(f"--{boundary}\r\n".encode("utf-8"))
        body.extend(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode("utf-8"))
        body.extend(f"{v}\r\n".encode("utf-8"))

    body.extend(f"--{boundary}\r\n".encode("utf-8"))
    body.extend(f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode("utf-8"))
    body.extend(f"Content-Type: {content_type}\r\n\r\n".encode("utf-8"))
    body.extend(file_bytes)
    body.extend(b"\r\n")
    body.extend(f"--{boundary}--\r\n".encode("utf-8"))

    url = f"{base_url}/api/collections/books/records"
    req = urllib.request.Request(
        url,
        data=bytes(body),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": f"multipart/form-data; boundary={boundary}"
        }
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            res = json.loads(resp.read().decode("utf-8"))
            logger.info(f"Successfully imported: '{title}' (ID: {res.get('id')})")
            return True
    except Exception as e:
        logger.error(f"Failed to upload '{title}': {e}")
        return False


def sync_once():
    """Run one synchronization pass."""
    db_path = os.path.join(CALIBRE_PATH, "metadata.db")
    if not os.path.exists(db_path):
        logger.warning(f"Calibre database not found at {db_path}. Scanning directory directly...")
        return sync_from_directory()

    token, user_id = authenticate_ownbook(OWNBOOK_URL, OWNBOOK_USER, OWNBOOK_PASSWORD)
    if not token or not user_id:
        logger.error("Skipping sync: authentication failed.")
        return 0

    existing_books = get_existing_books(OWNBOOK_URL, token)
    logger.info(f"Connected to OwnBook. Found {len(existing_books)} books already present.")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Query books from Calibre
    query = """
    SELECT b.id, b.title, b.path,
           (SELECT GROUP_CONCAT(a.name, ', ') FROM authors a JOIN books_authors_link bal ON a.id = bal.author WHERE bal.book = b.id) AS author,
           (SELECT c.text FROM comments c WHERE c.book = b.id) AS description
    FROM books b
    ORDER BY b.id ASC
    """
    cursor.execute(query)
    rows = cursor.fetchall()

    imported_count = 0
    for book_id, title, rel_path, author, description in rows:
        title_clean = (title or "").strip()
        if not title_clean:
            continue

        norm_title = title_clean.lower()
        if norm_title in existing_books:
            continue

        # Look for EPUB, PDF, or MOBI in data table for this book
        cursor.execute("SELECT format, name FROM data WHERE book = ? ORDER BY CASE format WHEN 'EPUB' THEN 1 WHEN 'PDF' THEN 2 ELSE 3 END", (book_id,))
        formats = cursor.fetchall()
        if not formats:
            continue

        chosen_format, file_name = formats[0]
        actual_file_path = os.path.join(CALIBRE_PATH, rel_path, f"{file_name}.{chosen_format.lower()}")
        if not os.path.exists(actual_file_path):
            continue

        logger.info(f"Importing Calibre book [{book_id}]: '{title_clean}' by {author} ({chosen_format})")
        if upload_book(OWNBOOK_URL, token, user_id, title_clean, author, description, actual_file_path):
            imported_count += 1
            existing_books[norm_title] = True
            time.sleep(1)  # small pause to allow PocketBase parser worker to breathe

    conn.close()
    logger.info(f"Sync pass completed. Imported {imported_count} new books.")
    return imported_count


def sync_from_directory():
    """Fallback directory scan if metadata.db is missing."""
    token, user_id = authenticate_ownbook(OWNBOOK_URL, OWNBOOK_USER, OWNBOOK_PASSWORD)
    if not token or not user_id:
        return 0

    existing_books = get_existing_books(OWNBOOK_URL, token)
    imported_count = 0
    for root, _, files in os.walk(CALIBRE_PATH):
        for f in files:
            ext = os.path.splitext(f)[1].lower()
            if ext in [".epub", ".pdf", ".mobi"]:
                full_path = os.path.join(root, f)
                title = os.path.splitext(f)[0]
                norm_title = title.lower()
                if norm_title in existing_books:
                    continue

                logger.info(f"Importing file: '{title}'")
                if upload_book(OWNBOOK_URL, token, user_id, title, "Unknown", "", full_path):
                    imported_count += 1
                    existing_books[norm_title] = True
                    time.sleep(1)
    return imported_count


def main():
    logger.info(f"Starting Calibre to OwnBook Sync Bridge")
    logger.info(f"Target OwnBook: {OWNBOOK_URL}")
    logger.info(f"Calibre Path: {CALIBRE_PATH}")
    logger.info(f"Sync interval: {SYNC_INTERVAL} seconds")

    # Wait for OwnBook to be ready
    for attempt in range(30):
        try:
            with urllib.request.urlopen(f"{OWNBOOK_URL}/api/health", timeout=5) as resp:
                if resp.status == 200:
                    logger.info("OwnBook is ready.")
                    break
        except Exception:
            logger.info("Waiting for OwnBook to start up...")
            time.sleep(3)

    if SYNC_INTERVAL <= 0:
        sync_once()
        return

    while True:
        try:
            sync_once()
        except Exception as e:
            logger.error(f"Unexpected error during sync: {e}")
        time.sleep(SYNC_INTERVAL)


if __name__ == "__main__":
    main()
