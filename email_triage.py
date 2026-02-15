#!/usr/bin/env python3
"""
Inbox Zero — Multi-account Gmail triage via IMAP.
Two-pass autonomous triage for large Gmail inboxes.
"""

import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import os
import re
import sys
import json
import csv
import argparse
import time
import shutil
from collections import deque, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from dotenv import load_dotenv

# Gmail can return very long lines for large batch fetches
imaplib._MAXLINE = 10_000_000

IMAP_SERVER = "imap.gmail.com"
BASE_OUTPUT_DIR = Path("triage_output")


# ── Account loading ──────────────────────────────────────────────


def load_accounts():
    """Load accounts from accounts.json, falling back to .env."""
    accounts_path = Path("accounts.json")
    if accounts_path.exists():
        with open(accounts_path) as f:
            data = json.load(f)
        if not data.get("accounts"):
            sys.exit("ERROR: accounts.json exists but has no accounts listed.")
        return data["accounts"]

    load_dotenv()
    addr = os.getenv("GMAIL_ADDRESS")
    pw = os.getenv("GMAIL_APP_PASSWORD")
    if not addr or not pw:
        sys.exit(
            "ERROR: No accounts.json found and .env is missing GMAIL_ADDRESS or GMAIL_APP_PASSWORD.\n"
            "Create accounts.json or .env — see project-inbox-zero.md for format."
        )
    name = addr.split("@")[0]
    return [{"name": name, "email": addr, "app_password": pw}]


def get_account(accounts, name=None):
    """Return a single account dict by name, or the first one."""
    if name:
        for a in accounts:
            if a["name"] == name:
                return a
        sys.exit(f"ERROR: No account named '{name}'. Available: {[a['name'] for a in accounts]}")
    return accounts[0]


def get_output_dir(account_name):
    """Return triage_output/<account_name>/, creating if needed."""
    d = BASE_OUTPUT_DIR / account_name
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── IMAP connection ─────────────────────────────────────────────


def is_gmail(account):
    """Check if account uses Gmail IMAP."""
    server = account.get("imap-server", IMAP_SERVER)
    return "gmail" in server.lower() or "google" in server.lower()


def connect(account):
    """Connect and authenticate to IMAP server."""
    server = account.get("imap-server", IMAP_SERVER)
    password = account.get("app_password") or account.get("mail_password")
    if not password:
        sys.exit(f"ERROR: No password found for {account['email']}. "
                 f"Set 'app_password' or 'mail_password' in accounts.json")
    try:
        mail = imaplib.IMAP4_SSL(server)
        mail.login(account["email"], password)
        return mail
    except imaplib.IMAP4.error as e:
        sys.exit(f"ERROR: IMAP login failed for {account['email']} on {server}: {e}")


def safe_disconnect(mail):
    """Logout gracefully."""
    try:
        mail.logout()
    except Exception:
        pass


# ── Header decoding ─────────────────────────────────────────────


def decode_header_value(value):
    """Safely decode an email header."""
    if value is None:
        return ""
    decoded_parts = decode_header(value)
    result = []
    for part, charset in decoded_parts:
        if isinstance(part, bytes):
            try:
                result.append(part.decode(charset or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                result.append(part.decode("utf-8", errors="replace"))
        else:
            result.append(str(part))
    return " ".join(result)


def get_sender_email(from_header):
    """Extract just the email address from a From header."""
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].lower()
    return from_header.lower().strip()


def get_sender_name(from_header):
    """Extract display name from a From header."""
    if "<" in from_header:
        name = from_header.split("<")[0].strip().strip('"').strip("'")
        return name if name else get_sender_email(from_header)
    return from_header.strip()


# ── Checkpoint / resume ─────────────────────────────────────────


def save_checkpoint(path, data):
    """Save progress checkpoint atomically."""
    data["timestamp"] = datetime.now(timezone.utc).isoformat()
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, default=str)
    tmp.rename(path)


def load_checkpoint(path):
    """Load checkpoint if it exists."""
    if not path.exists():
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return None


# ── Pass 1: Metadata fetch ──────────────────────────────────────


def fetch_metadata(mail, checkpoint_path=None):
    """
    Fetch metadata (sender, subject, date, flags) for all INBOX messages.
    Batched for speed. Saves checkpoints for resume.
    """
    mail.select("INBOX", readonly=True)
    _, data = mail.search(None, "ALL")
    msg_ids = data[0].split()

    if not msg_ids:
        print("  INBOX is empty.")
        return []

    # Check for checkpoint
    messages = []
    fetched_ids = set()
    if checkpoint_path:
        cp = load_checkpoint(checkpoint_path)
        if cp and "messages" in cp:
            messages = cp["messages"]
            fetched_ids = set(m["msg_id"] for m in messages)
            print(f"  Resuming from checkpoint: {len(messages)} already fetched")

    remaining_ids = [mid for mid in msg_ids if mid.decode() not in fetched_ids]
    total = len(msg_ids)
    print(f"  Fetching metadata for {len(remaining_ids)} messages ({len(fetched_ids)} cached, {total} total)...", flush=True)

    batch_size = 500
    for i in range(0, len(remaining_ids), batch_size):
        batch = remaining_ids[i:i + batch_size]
        id_range = b",".join(batch)
        _, batch_data = mail.fetch(id_range, "(FLAGS BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])")

        for item in batch_data:
            if item is None or not isinstance(item, tuple):
                continue

            # Extract sequence number from response — e.g. b'12345 (FLAGS ...'
            seq_info = item[0]
            if isinstance(seq_info, bytes):
                seq_num = seq_info.split(b" ")[0].decode()
            else:
                continue

            raw_header = item[1]
            try:
                msg = email.message_from_bytes(raw_header)
            except Exception:
                continue

            from_raw = decode_header_value(msg.get("From", ""))
            subject = decode_header_value(msg.get("Subject", "(no subject)"))
            date_raw = msg.get("Date", "")

            try:
                date_parsed = parsedate_to_datetime(date_raw)
            except Exception:
                date_parsed = None

            raw_flags = seq_info.decode() if isinstance(seq_info, bytes) else str(seq_info)
            is_unread = "\\Seen" not in raw_flags

            messages.append({
                "msg_id": seq_num,
                "from_email": get_sender_email(from_raw),
                "from_name": get_sender_name(from_raw),
                "subject": subject,
                "date": date_parsed.isoformat() if date_parsed else date_raw,
                "is_unread": is_unread,
            })

        done = len(fetched_ids) + min(i + batch_size, len(remaining_ids))
        print(f"    ...{done}/{total}")

        # Checkpoint every 500
        if checkpoint_path:
            save_checkpoint(checkpoint_path, {"messages": messages})

    return messages


def pass1_sender_analysis(messages, output_dir, shared_rules=None):
    """
    Analyse senders by frequency. Auto-apply shared rules.
    Returns (sorted_senders, summary).
    """
    shared_archive = set()
    if shared_rules:
        shared_archive = set(s.lower() for s in shared_rules.get("archive_senders", []))
        shared_domains = set(d.lower() for d in shared_rules.get("archive_domains", []))
    else:
        shared_domains = set()

    sender_stats = {}
    for msg in messages:
        addr = msg["from_email"]
        if addr not in sender_stats:
            sender_stats[addr] = {
                "email": addr,
                "name": msg["from_name"],
                "count": 0,
                "unread": 0,
                "subjects": [],
                "shared_rule_match": addr in shared_archive or any(
                    addr.endswith("@" + d) for d in shared_domains
                ),
            }
        s = sender_stats[addr]
        s["count"] += 1
        if msg.get("is_unread"):
            s["unread"] += 1
        if len(s["subjects"]) < 5:
            s["subjects"].append(msg["subject"])

    sorted_senders = sorted(sender_stats.values(), key=lambda x: x["count"], reverse=True)

    # Write sender report CSV
    report_path = output_dir / "pass1_sender_report.csv"
    with open(report_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "name", "total", "unread", "shared_rule", "sample_subjects"])
        for s in sorted_senders:
            writer.writerow([
                s["email"], s["name"], s["count"], s["unread"],
                "YES" if s["shared_rule_match"] else "",
                " | ".join(s["subjects"][:3]),
            ])

    # Count shared rule auto-archives
    shared_auto = sum(1 for m in messages if
        m["from_email"] in shared_archive or
        any(m["from_email"].endswith("@" + d) for d in shared_domains))

    summary = {
        "total_messages": len(messages),
        "total_unread": sum(1 for m in messages if m.get("is_unread")),
        "unique_senders": len(sender_stats),
        "top_20_senders": [
            {"email": s["email"], "name": s["name"], "count": s["count"], "unread": s["unread"]}
            for s in sorted_senders[:20]
        ],
        "senders_with_10_plus": len([s for s in sorted_senders if s["count"] >= 10]),
        "senders_with_50_plus": len([s for s in sorted_senders if s["count"] >= 50]),
        "shared_rules_auto_archived": shared_auto,
    }

    summary_path = output_dir / "pass1_summary.json"
    with open(summary_path, "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n  Pass 1 complete:")
    print(f"    Total messages:    {summary['total_messages']}")
    print(f"    Total unread:      {summary['total_unread']}")
    print(f"    Unique senders:    {summary['unique_senders']}")
    print(f"    10+ email senders: {summary['senders_with_10_plus']}")
    print(f"    50+ email senders: {summary['senders_with_50_plus']}")
    if shared_auto:
        print(f"    Auto-archived by shared rules: {shared_auto}")
    print(f"\n    Reports → {output_dir}/")

    return sorted_senders, summary


# ── Pass 2: Batch body fetch ────────────────────────────────────


def extract_plain_text(raw_body, max_chars=300):
    """Extract plain text from a raw email body, truncated."""
    try:
        msg = email.message_from_bytes(raw_body)
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    charset = part.get_content_charset() or "utf-8"
                    return part.get_payload(decode=True).decode(charset, errors="replace")[:max_chars]
        else:
            charset = msg.get_content_charset() or "utf-8"
            payload = msg.get_payload(decode=True)
            if payload:
                return payload.decode(charset, errors="replace")[:max_chars]
    except Exception:
        pass
    return ""


def fetch_bodies_batch(mail, msg_ids, max_chars=300, batch_size=50, checkpoint_path=None):
    """
    Fetch plain text body previews in batches.
    Smaller batches (10) for slow servers, checkpoint after every batch.
    """
    results = {}

    if checkpoint_path:
        cp = load_checkpoint(checkpoint_path)
        if cp and "bodies" in cp:
            results = cp["bodies"]
            msg_ids = [mid for mid in msg_ids if mid not in results]
            print(f"    Resuming: {len(results)} bodies cached, {len(msg_ids)} remaining", flush=True)

    total = len(msg_ids) + len(results)

    for i in range(0, len(msg_ids), batch_size):
        batch = msg_ids[i:i + batch_size]
        id_set = ",".join(batch)

        try:
            # Set a 120s timeout per batch to avoid infinite hangs
            old_timeout = mail.socket().gettimeout()
            mail.socket().settimeout(120)
            _, batch_data = mail.fetch(id_set.encode(), "(BODY.PEEK[TEXT])")
            mail.socket().settimeout(old_timeout)
        except (TimeoutError, OSError) as e:
            print(f"    Warning: batch timed out at offset {i}, retrying with smaller batch: {e}", flush=True)
            # Retry one-by-one for this batch
            for single_id in batch:
                try:
                    mail.socket().settimeout(60)
                    _, single_data = mail.fetch(single_id.encode(), "(BODY.PEEK[TEXT])")
                    mail.socket().settimeout(old_timeout)
                    for item in (single_data or []):
                        if item is None or not isinstance(item, tuple):
                            continue
                        seq_info = item[0]
                        if isinstance(seq_info, bytes):
                            seq_num = seq_info.split(b" ")[0].decode()
                            results[seq_num] = extract_plain_text(item[1], max_chars)
                except Exception:
                    pass
            done = len(results)
            print(f"    Bodies: {done}/{total} (after retry)", flush=True)
            if checkpoint_path:
                save_checkpoint(checkpoint_path, {"bodies": results})
            continue
        except Exception as e:
            print(f"    Warning: batch body fetch failed at offset {i}: {e}", flush=True)
            continue

        for item in batch_data:
            if item is None or not isinstance(item, tuple):
                continue
            seq_info = item[0]
            if isinstance(seq_info, bytes):
                seq_num = seq_info.split(b" ")[0].decode()
            else:
                continue
            results[seq_num] = extract_plain_text(item[1], max_chars)

        done = len(results)
        print(f"    Bodies: {done}/{total}", flush=True)

        # Checkpoint every batch for slow servers
        if checkpoint_path:
            save_checkpoint(checkpoint_path, {"bodies": results})

    if checkpoint_path:
        save_checkpoint(checkpoint_path, {"bodies": results})

    return results


def pass2_body_analysis(mail, messages, archive_senders, output_dir):
    """
    For messages NOT auto-archived by sender, fetch bodies in batch
    and write pass2_remaining.json for CC to classify.
    """
    archive_set = set(s.lower() for s in archive_senders)
    remaining = [m for m in messages if m["from_email"] not in archive_set]

    print(f"\n  Pass 2: {len(remaining)} messages need body analysis")
    if not remaining:
        print("    Nothing to analyse — all messages covered by sender rules.")
        return []

    # Batch fetch bodies
    mail.select("INBOX", readonly=True)
    remaining_ids = [m["msg_id"] for m in remaining]
    cp_path = output_dir / "checkpoint_bodies.json"
    bodies = fetch_bodies_batch(mail, remaining_ids, checkpoint_path=cp_path)

    # Build output
    results = []
    for msg in remaining:
        results.append({
            "msg_id": msg["msg_id"],
            "from_email": msg["from_email"],
            "from_name": msg["from_name"],
            "subject": msg["subject"],
            "date": msg["date"],
            "is_unread": msg.get("is_unread"),
            "body_preview": bodies.get(msg["msg_id"], ""),
        })

    output_path = output_dir / "pass2_remaining.json"
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    print(f"    Saved {len(results)} messages → {output_path}")
    return results


# ── Archiving ───────────────────────────────────────────────────


def verify_archive_safety(mail, pre_allmail_count, account):
    """
    After archiving from INBOX, check All Mail count hasn't decreased.
    Gmail-only — non-Gmail uses COPY+DELETE so safety is inherent.
    """
    if not is_gmail(account):
        return True  # non-Gmail: we COPY before DELETE, so always safe
    try:
        mail.select('"[Gmail]/All Mail"', readonly=True)
        _, data = mail.search(None, "ALL")
        post_count = len(data[0].split()) if data[0] else 0
        mail.select("INBOX")  # switch back
        return post_count >= pre_allmail_count
    except Exception:
        mail.select("INBOX")
        return False


def ensure_archive_folder(mail):
    """Create 'Archive' folder if it doesn't exist (non-Gmail servers)."""
    typ, folders = mail.list()
    for f in (folders or []):
        decoded = f.decode() if isinstance(f, bytes) else str(f)
        # Match both quoted ("Archive") and unquoted (Archive) folder names
        if '"Archive"' in decoded or decoded.rstrip().endswith(" Archive") or decoded.rstrip().endswith("/Archive"):
            return "Archive"
    # Try to create it
    typ, _ = mail.create("Archive")
    if typ == "OK":
        return "Archive"
    # Some servers use INBOX.Archive
    typ, _ = mail.create("INBOX.Archive")
    if typ == "OK":
        return "INBOX.Archive"
    return None


def scan_inbox_uids_by_sender(mail, target_senders):
    """
    Scan INBOX using UIDs (stable across expunges) and return UIDs
    whose sender matches the target set.
    """
    mail.select("INBOX", readonly=True)
    _, data = mail.uid("search", None, "ALL")
    all_uids = data[0].split() if data[0] else []

    if not all_uids:
        return []

    matched_uids = []
    batch_size = 500
    for i in range(0, len(all_uids), batch_size):
        batch = all_uids[i:i + batch_size]
        uid_set = b",".join(batch)
        _, batch_data = mail.uid("fetch", uid_set, "(BODY.PEEK[HEADER.FIELDS (FROM)])")

        for item in batch_data:
            if item is None or not isinstance(item, tuple):
                continue
            resp_line = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
            uid_val = None
            if "UID " in resp_line:
                uid_val = resp_line.split("UID ")[1].split(" ")[0].split(")")[0]
            if not uid_val:
                continue

            raw_header = item[1]
            try:
                msg = email.message_from_bytes(raw_header)
            except Exception:
                continue

            from_raw = decode_header_value(msg.get("From", ""))
            sender = get_sender_email(from_raw)

            if sender in target_senders:
                matched_uids.append(uid_val)

        print(f"    Scanned {min(i + batch_size, len(all_uids))}/{len(all_uids)}, matched: {len(matched_uids)}")

    return matched_uids


def archive_messages(mail, archive_senders, dry_run=True, batch_size=200, account=None):
    """
    Archive messages from INBOX by scanning for senders and using UIDs.
    UIDs are stable across expunges — no sequence number shift issues.
    Gmail: +FLAGS \\Deleted + EXPUNGE on INBOX = remove INBOX label.
    Non-Gmail: COPY to Archive folder, then DELETE + EXPUNGE.
    """
    gmail = is_gmail(account) if account else True
    print(f"    Scanning INBOX for messages to archive...")
    target = set(s.lower() for s in archive_senders)
    matched_uids = scan_inbox_uids_by_sender(mail, target)

    if not matched_uids:
        print("  No messages to archive.")
        return 0

    if dry_run:
        print(f"\n  [DRY RUN] Would archive {len(matched_uids)} messages")
        print(f"  Run with --execute to perform the archive.")
        return 0

    pre_allmail_count = 0
    archive_folder = None

    if gmail:
        # Snapshot All Mail count before we start
        mail.select('"[Gmail]/All Mail"', readonly=True)
        _, data = mail.search(None, "ALL")
        pre_allmail_count = len(data[0].split()) if data[0] else 0
    else:
        # Non-Gmail: ensure Archive folder exists for COPY
        archive_folder = ensure_archive_folder(mail)
        if not archive_folder:
            print("    ERROR: Could not create Archive folder. Aborting.")
            return 0
        print(f"    Using folder '{archive_folder}' for archived messages")

    # Work in INBOX
    mail.select("INBOX")
    archived = 0

    for i in range(0, len(matched_uids), batch_size):
        batch = matched_uids[i:i + batch_size]
        uid_set = ",".join(batch)

        if not gmail:
            # Non-Gmail: COPY to Archive first
            typ, _ = mail.uid("copy", uid_set, archive_folder)
            if typ != "OK":
                print(f"    ERROR: UID COPY failed for batch at offset {i}")
                continue

        typ, _ = mail.uid("store", uid_set, "+FLAGS", "\\Deleted")
        if typ != "OK":
            print(f"    ERROR: UID STORE failed for batch at offset {i}")
            continue

        archived += len(batch)
        if archived % 1000 == 0 or i + batch_size >= len(matched_uids):
            print(f"    Flagged: {archived}/{len(matched_uids)}")

    # Single expunge
    print("    Expunging...")
    mail.expunge()

    # Safety check
    if not verify_archive_safety(mail, pre_allmail_count, account or {}):
        print("\n  WARNING: All Mail count decreased after archive!")
        print("  Check Gmail Settings > IMAP:")
        print("    - Auto-Expunge: ON")
        print("    - When deleted: 'Archive the message' (default)")
    else:
        print("    Safety check passed — All Mail count stable")

    print(f"    Archived: {archived}")

    return archived


# ── Shared rules ────────────────────────────────────────────────


def load_shared_rules():
    """Load shared_rules.json if it exists."""
    path = Path("shared_rules.json")
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"archive_senders": [], "archive_domains": []}


def save_shared_rules(rules):
    """Save shared_rules.json."""
    with open("shared_rules.json", "w") as f:
        json.dump(rules, f, indent=2)


def merge_rules_command():
    """
    Scan all account archive_rules.json files.
    Find senders that appear in 2+ accounts and offer to add to shared rules.
    """
    shared = load_shared_rules()
    existing_shared = set(s.lower() for s in shared.get("archive_senders", []))

    sender_accounts = {}
    for account_dir in BASE_OUTPUT_DIR.iterdir():
        if not account_dir.is_dir():
            continue
        rules_path = account_dir / "archive_rules.json"
        if not rules_path.exists():
            continue
        with open(rules_path) as f:
            rules = json.load(f)
        for sender in rules.get("archive_senders", []):
            sender = sender.lower()
            if sender not in sender_accounts:
                sender_accounts[sender] = []
            sender_accounts[sender].append(account_dir.name)

    # Find senders in 2+ accounts not already in shared rules
    candidates = {
        s: accts for s, accts in sender_accounts.items()
        if len(accts) >= 2 and s not in existing_shared
    }

    if not candidates:
        print("  No new cross-account senders found.")
        return

    print(f"\n  Found {len(candidates)} senders appearing in 2+ accounts:\n")
    new_senders = []
    for sender, accts in sorted(candidates.items(), key=lambda x: len(x[1]), reverse=True):
        print(f"    {sender}  ({', '.join(accts)})")
        new_senders.append(sender)

    shared["archive_senders"] = sorted(set(shared.get("archive_senders", []) + new_senders))
    save_shared_rules(shared)
    print(f"\n  Added {len(new_senders)} senders to shared_rules.json")


# ── Status ──────────────────────────────────────────────────────


def status_command(account):
    """Show account status — connection test and triage progress."""
    print(f"\n  Account: {account['name']} ({account['email']})")

    mail = connect(account)
    mail.select("INBOX", readonly=True)
    _, data = mail.search(None, "ALL")
    total = len(data[0].split()) if data[0] else 0
    _, unseen_data = mail.search(None, "UNSEEN")
    unread = len(unseen_data[0].split()) if unseen_data[0] else 0
    safe_disconnect(mail)

    print(f"    INBOX total:  {total}")
    print(f"    INBOX unread: {unread}")

    output_dir = BASE_OUTPUT_DIR / account["name"]
    if (output_dir / "pass1_summary.json").exists():
        print(f"    Pass 1: done")
    else:
        print(f"    Pass 1: not started")
    if (output_dir / "archive_rules.json").exists():
        print(f"    Archive rules: created")
    else:
        print(f"    Archive rules: pending")
    if (output_dir / "pass2_remaining.json").exists():
        print(f"    Pass 2: done")
    else:
        print(f"    Pass 2: not started")


# ── Monitor ─────────────────────────────────────────────────────


def _count_checkpoint_bodies(cp_path):
    """Read checkpoint file and return body count without loading full data."""
    if not cp_path.exists():
        return 0
    try:
        with open(cp_path) as f:
            data = json.load(f)
        return len(data.get("bodies", {}))
    except (json.JSONDecodeError, IOError):
        return 0


def _count_checkpoint_metadata(cp_path):
    """Read metadata checkpoint and return message count."""
    if not cp_path.exists():
        return 0
    try:
        with open(cp_path) as f:
            data = json.load(f)
        return len(data.get("messages", []))
    except (json.JSONDecodeError, IOError):
        return 0


def _get_remaining_count(output_dir):
    """Calculate how many messages need body fetch for an account."""
    msg_path = output_dir / "all_messages.json"
    rules_path = output_dir / "archive_rules.json"

    if not msg_path.exists():
        return None

    try:
        with open(msg_path) as f:
            messages = json.load(f)
    except (json.JSONDecodeError, IOError):
        return None

    archive_senders = set()
    if rules_path.exists():
        try:
            with open(rules_path) as f:
                rules = json.load(f)
            archive_senders = set(s.lower() for s in rules.get("archive_senders", []))
        except (json.JSONDecodeError, IOError):
            pass

    # Also include shared rules
    shared = load_shared_rules()
    archive_senders.update(s.lower() for s in shared.get("archive_senders", []))

    remaining = [m for m in messages if m["from_email"] not in archive_senders]
    return len(remaining)


def _get_total_messages(output_dir):
    """Get total inbox message count from pass1 summary."""
    summary_path = output_dir / "pass1_summary.json"
    if not summary_path.exists():
        return None
    try:
        with open(summary_path) as f:
            return json.load(f).get("total_messages")
    except (json.JSONDecodeError, IOError):
        return None


def _progress_bar(fraction, width=30):
    """Render a text progress bar."""
    filled = int(width * fraction)
    bar = "\u2588" * filled + "\u2591" * (width - filled)
    return f"[{bar}]"


def _format_eta(seconds):
    """Format seconds into human-readable ETA."""
    if seconds is None or seconds <= 0:
        return "--:--"
    if seconds > 86400:
        return f"{seconds / 3600:.0f}h"
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}h{m:02d}m"
    return f"{m}m{s:02d}s"


def _detect_phase(output_dir):
    """Detect which phase an account is in."""
    has_p1_summary = (output_dir / "pass1_summary.json").exists()
    has_rules = (output_dir / "archive_rules.json").exists()
    has_p2_remaining = (output_dir / "pass2_remaining.json").exists()
    has_classification = (output_dir / "pass2_classification.json").exists()

    if has_classification:
        return "done", "Triage complete"
    if has_p2_remaining:
        return "p2-done", "Pass 2 done, awaiting classification"
    if has_rules:
        cp = output_dir / "checkpoint_bodies.json"
        if cp.exists():
            return "p2-fetch", "Pass 2: fetching bodies"
        return "p2-pending", "Pass 2: ready to run"
    if has_p1_summary:
        return "p1-done", "Pass 1 done, awaiting rules"
    cp = output_dir / "checkpoint_metadata.json"
    if cp.exists():
        return "p1-fetch", "Pass 1: fetching metadata"
    return "idle", "Not started"


def monitor_command(interval=3):
    """
    Live dashboard showing triage progress for all accounts.
    Reads checkpoint files only — no IMAP connection needed.
    """
    # Track rate history per account: deque of (timestamp, count)
    rate_history = {}
    term_width = shutil.get_terminal_size((80, 24)).columns

    print("Starting monitor... (Ctrl+C to exit)\n")

    try:
        while True:
            lines = []
            now = time.time()
            now_str = datetime.now().strftime("%H:%M:%S")

            lines.append(f"  Inbox Zero Monitor  |  {now_str}  |  refresh: {interval}s")
            lines.append("─" * min(term_width, 72))

            # Scan all account directories
            if not BASE_OUTPUT_DIR.exists():
                lines.append("  No triage_output/ directory found. Run pass1 first.")
            else:
                account_dirs = sorted(
                    [d for d in BASE_OUTPUT_DIR.iterdir() if d.is_dir()],
                    key=lambda d: d.name,
                )

                if not account_dirs:
                    lines.append("  No account data found.")
                else:
                    for acct_dir in account_dirs:
                        name = acct_dir.name
                        phase, phase_label = _detect_phase(acct_dir)

                        lines.append(f"\n  {name}")
                        lines.append(f"  Phase: {phase_label}")

                        if phase == "p1-fetch":
                            # Show metadata fetch progress
                            total = _get_total_messages(acct_dir)
                            cp_path = acct_dir / "checkpoint_metadata.json"
                            fetched = _count_checkpoint_metadata(cp_path)

                            if total and total > 0:
                                pct = fetched / total
                                bar = _progress_bar(pct)
                                lines.append(f"  {bar} {pct * 100:5.1f}%  ({fetched:,} / {total:,})")
                            else:
                                lines.append(f"  Fetched: {fetched:,} messages")

                        elif phase == "p2-fetch":
                            # Show body fetch progress
                            cp_path = acct_dir / "checkpoint_bodies.json"
                            fetched = _count_checkpoint_bodies(cp_path)
                            total_remaining = _get_remaining_count(acct_dir)
                            total_inbox = _get_total_messages(acct_dir)

                            if total_remaining and total_remaining > 0:
                                pct = fetched / total_remaining
                                bar = _progress_bar(pct)

                                # Rate calculation
                                if name not in rate_history:
                                    rate_history[name] = deque(maxlen=60)
                                rate_history[name].append((now, fetched))
                                history = rate_history[name]

                                rate_str = "---"
                                eta_str = "--:--"
                                if len(history) >= 2:
                                    # Use 30-second window for smoothing
                                    oldest = history[0]
                                    dt = now - oldest[0]
                                    dc = fetched - oldest[1]
                                    if dt > 0 and dc > 0:
                                        rate = dc / dt
                                        rate_str = f"{rate * 60:.0f}/min"
                                        left = total_remaining - fetched
                                        eta_str = _format_eta(left / rate)

                                archived = (total_inbox - total_remaining) if total_inbox else 0
                                lines.append(f"  {bar} {pct * 100:5.1f}%  ({fetched:,} / {total_remaining:,})")
                                lines.append(f"  Rate: {rate_str}  |  ETA: {eta_str}  |  Auto-archived: {archived:,}")
                            else:
                                lines.append(f"  Bodies fetched: {fetched:,}")

                        elif phase in ("p1-done", "p2-pending"):
                            total = _get_total_messages(acct_dir)
                            if total:
                                lines.append(f"  Inbox: {total:,} messages")

                        elif phase == "p2-done":
                            total_remaining = _get_remaining_count(acct_dir)
                            if total_remaining:
                                lines.append(f"  {total_remaining:,} messages ready for classification")

                        elif phase == "done":
                            lines.append(f"  All passes complete")

            lines.append("\n" + "─" * min(term_width, 72))
            lines.append("  Ctrl+C to exit")

            # Clear screen and print
            print("\033[2J\033[H", end="")
            print("\n".join(lines))

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\n  Monitor stopped.")


# ── Phase 2: Pattern Refinement ─────────────────────────────────


# Categories that should never be archived regardless of patterns
KEEP_CATEGORIES = {"urgent", "action_needed"}
# Categories safe for time-decay / dedup pruning
ARCHIVABLE_CATEGORIES = {"archive", "reference"}


def _normalise_subject(subj):
    """Strip Re:/Fwd: prefixes and collapse whitespace."""
    subj = re.sub(r'^(Re|Fwd|FW|Fw)\s*:\s*', '', subj, flags=re.IGNORECASE).strip()
    return re.sub(r'\s+', ' ', subj)


def _first_n_words(text, n=4):
    """Return the first N words lowercased."""
    words = text.split()[:n]
    return " ".join(w.lower() for w in words)


def _jaccard(a, b):
    """Word-level Jaccard similarity between two strings."""
    sa = set(a.lower().split())
    sb = set(b.lower().split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _cluster_subjects(subjects):
    """
    Cluster a list of subjects by common prefix (first 4 words).
    Returns list of {"pattern": str, "count": int, "subjects": [str]}.
    """
    groups = defaultdict(list)
    for subj in subjects:
        norm = _normalise_subject(subj)
        key = _first_n_words(norm, 4)
        groups[key].append(subj)

    clusters = []
    for prefix, subjs in sorted(groups.items(), key=lambda x: -len(x[1])):
        # Use the most common raw subject as the pattern label
        clusters.append({
            "pattern": prefix if prefix else "(empty subject)",
            "count": len(subjs),
            "subjects": subjs,
        })
    return clusters


def _parse_date(date_str):
    """Parse an ISO date string to timezone-aware datetime, returning None on failure."""
    if not date_str:
        return None
    try:
        dt = datetime.fromisoformat(date_str)
    except (ValueError, TypeError):
        try:
            dt = parsedate_to_datetime(date_str)
        except Exception:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _days_old(date_str, now=None):
    """Return how many days old a message is, or None if unparseable."""
    dt = _parse_date(date_str)
    if dt is None:
        return None
    if now is None:
        now = datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (now - dt).days


def _is_notification_like(msg):
    """Heuristic: noreply/notification sender or subject patterns."""
    addr = msg.get("from_email", "")
    subj = msg.get("subject", "").lower()
    if any(k in addr for k in ["noreply", "no-reply", "notify", "notification", "alerts", "mailer-daemon"]):
        return True
    if any(k in subj for k in ["notification", "alert", "reminder", "update", "digest"]):
        return True
    return False


def _is_receipt_like(msg):
    """Heuristic: receipt/confirmation/order subject patterns."""
    subj = msg.get("subject", "").lower()
    return any(k in subj for k in ["receipt", "confirmation", "order", "invoice", "payment", "shipped", "delivered"])


def _is_newsletter_like(msg):
    """Heuristic: newsletter/digest/marketing patterns."""
    subj = msg.get("subject", "").lower()
    addr = msg.get("from_email", "")
    reason = msg.get("reason", "").lower()
    if "newsletter" in subj or "digest" in subj or "weekly" in subj or "monthly" in subj:
        return True
    if "marketing" in reason or "newsletter" in reason or "promotional" in reason:
        return True
    if any(k in addr for k in ["newsletter", "digest", "marketing", "campaign", "promo"]):
        return True
    return False


def _is_security_alert(msg):
    """Heuristic: security alert patterns."""
    subj = msg.get("subject", "").lower()
    return any(k in subj for k in ["security alert", "sign-in", "signin", "login", "password", "verification code", "2fa", "two-factor"])


def _is_financial(msg):
    """Heuristic: financial records that should always be kept."""
    reason = msg.get("reason", "").lower()
    subj = msg.get("subject", "").lower()
    if any(k in reason for k in ["financial", "tax", "hmrc", "bank", "accountant", "invoice"]):
        return True
    if any(k in subj for k in ["tax", "hmrc", "p60", "p45", "self assessment", "statement", "bank"]):
        return True
    return False


def phase2_analyse(output_dir):
    """
    Analyse remaining messages for subject patterns, time decay, and dedup.
    Reads pass2_classification.json (preferred) or pass2_remaining.json.
    Writes phase2_analysis.json.
    """
    now = datetime.now(timezone.utc)

    # Load data — prefer classification file (has category/reason)
    class_path = output_dir / "pass2_classification.json"
    remain_path = output_dir / "pass2_remaining.json"

    if class_path.exists():
        with open(class_path) as f:
            messages = json.load(f)
        print(f"  Loaded {len(messages)} messages from pass2_classification.json")
    elif remain_path.exists():
        with open(remain_path) as f:
            messages = json.load(f)
        print(f"  Loaded {len(messages)} messages from pass2_remaining.json (no classification)")
    else:
        sys.exit(f"ERROR: No pass2 data found in {output_dir}. Run pass2 first.")

    # Separate already-classified archive vs rest
    already_archive = [m for m in messages if m.get("category") == "archive"]
    remaining = [m for m in messages if m.get("category") != "archive"]

    print(f"  Already classified as archive: {len(already_archive)}")
    print(f"  Remaining to analyse: {len(remaining)}")

    # ── Subject pattern clusters ──
    sender_groups = defaultdict(list)
    for msg in remaining:
        sender_groups[msg["from_email"]].append(msg)

    sender_patterns = []
    for sender_email, msgs in sorted(sender_groups.items(), key=lambda x: -len(x[1])):
        subjects = [m["subject"] for m in msgs]
        clusters = _cluster_subjects(subjects)

        dates = [_parse_date(m["date"]) for m in msgs]
        dates = [d for d in dates if d]

        pattern_list = []
        for cl in clusters:
            cl_dates = []
            for m in msgs:
                if m["subject"] in cl["subjects"]:
                    d = _parse_date(m["date"])
                    if d:
                        cl_dates.append(d)

            pattern_list.append({
                "pattern": cl["pattern"],
                "count": cl["count"],
                "oldest": min(cl_dates).isoformat() if cl_dates else None,
                "newest": max(cl_dates).isoformat() if cl_dates else None,
            })

        sender_patterns.append({
            "sender": sender_email,
            "sender_name": msgs[0].get("from_name", ""),
            "total": len(msgs),
            "patterns": pattern_list,
        })

    # ── Time decay candidates ──
    time_decay = {
        "notifications_over_7d": [],
        "receipts_over_90d": [],
        "security_over_30d": [],
        "newsletters_over_14d": [],
        "older_than_12mo": [],
    }

    for msg in remaining:
        cat = msg.get("category", "")
        if cat in KEEP_CATEGORIES:
            continue

        days = _days_old(msg.get("date"), now)
        if days is None:
            continue

        # Skip financial records from time decay
        if _is_financial(msg):
            continue

        msg_ref = {"msg_id": msg["msg_id"], "from_email": msg["from_email"],
                    "subject": msg["subject"], "date": msg.get("date"), "days_old": days}

        if _is_notification_like(msg) and days > 7:
            time_decay["notifications_over_7d"].append(msg_ref)
        elif _is_receipt_like(msg) and days > 90 and not _is_financial(msg):
            time_decay["receipts_over_90d"].append(msg_ref)
        elif _is_security_alert(msg) and days > 30:
            time_decay["security_over_30d"].append(msg_ref)
        elif _is_newsletter_like(msg) and days > 14:
            time_decay["newsletters_over_14d"].append(msg_ref)

        if days > 365:
            time_decay["older_than_12mo"].append(msg_ref)

    # ── Dedup candidates ──
    # Same sender, 5+ similar subjects within 24h window
    dedup_groups = []
    for sender_email, msgs in sender_groups.items():
        if len(msgs) < 5:
            continue

        # Sort by date
        dated = [(m, _parse_date(m.get("date"))) for m in msgs]
        dated = [(m, d) for m, d in dated if d is not None]
        dated.sort(key=lambda x: x[1])

        # Sliding window for bursts
        for i in range(len(dated)):
            burst = [dated[i]]
            for j in range(i + 1, len(dated)):
                if (dated[j][1] - dated[i][1]) <= timedelta(hours=24):
                    # Check similarity
                    subj_i = _normalise_subject(dated[i][0]["subject"])
                    subj_j = _normalise_subject(dated[j][0]["subject"])
                    if (_first_n_words(subj_i) == _first_n_words(subj_j) or
                            _jaccard(subj_i, subj_j) >= 0.6):
                        burst.append(dated[j])
                else:
                    break

            if len(burst) >= 5:
                # Sort burst by date, keep newest
                burst.sort(key=lambda x: x[1])
                keep = burst[-1]
                archive = burst[:-1]
                group_key = f"{sender_email}|{_first_n_words(burst[0][0]['subject'])}"

                # Avoid duplicate groups
                existing_keys = {g["group_key"] for g in dedup_groups}
                if group_key not in existing_keys:
                    dedup_groups.append({
                        "group_key": group_key,
                        "sender": sender_email,
                        "pattern": _first_n_words(burst[0][0]["subject"]),
                        "total_in_burst": len(burst),
                        "keep_msg_id": keep[0]["msg_id"],
                        "archive_msg_ids": [a[0]["msg_id"] for a in archive],
                    })

    # ── Collect all msg_ids targeted for archive ──
    archive_ids = set()

    # From classification
    for m in already_archive:
        archive_ids.add(m["msg_id"])

    # From time decay (exclude older_than_12mo — that's flagged for review, not auto-archive)
    td_ids = set()
    for bucket_name, bucket in time_decay.items():
        if bucket_name == "older_than_12mo":
            continue  # flag for review only
        for m in bucket:
            td_ids.add(m["msg_id"])
    archive_ids.update(td_ids)

    # From dedup
    dedup_ids = set()
    for g in dedup_groups:
        dedup_ids.update(g["archive_msg_ids"])
    archive_ids.update(dedup_ids)

    # ── Keep IDs: everything not targeted ──
    all_ids = {m["msg_id"] for m in messages}
    keep_ids = all_ids - archive_ids

    # ── Categorise kept messages ──
    keep_categories = defaultdict(int)
    for msg in messages:
        if msg["msg_id"] in keep_ids:
            cat = msg.get("category", "uncategorised")
            keep_categories[cat] += 1

    # ── Build output ──
    analysis = {
        "account": output_dir.name,
        "generated": now.isoformat(),
        "total_remaining": len(messages),
        "sender_patterns": sender_patterns,
        "time_decay_candidates": {
            "notifications_over_7d": len(time_decay["notifications_over_7d"]),
            "receipts_over_90d": len(time_decay["receipts_over_90d"]),
            "security_over_30d": len(time_decay["security_over_30d"]),
            "newsletters_over_14d": len(time_decay["newsletters_over_14d"]),
            "older_than_12mo": len(time_decay["older_than_12mo"]),
            "details": time_decay,
        },
        "dedup_candidates": {
            "burst_groups": len(dedup_groups),
            "total_duplicates": sum(len(g["archive_msg_ids"]) for g in dedup_groups),
            "groups": dedup_groups,
        },
        "summary": {
            "already_classified_archive": len(already_archive),
            "time_decay_archive": len(td_ids),
            "dedup_archive": len(dedup_ids),
            "flagged_for_review_12mo": len(time_decay["older_than_12mo"]),
            "total_would_archive": len(archive_ids),
            "total_would_keep": len(keep_ids),
            "keep_by_category": dict(keep_categories),
        },
        "archive_msg_ids": sorted(archive_ids),
        "keep_msg_ids": sorted(keep_ids),
    }

    out_path = output_dir / "phase2_analysis.json"
    with open(out_path, "w") as f:
        json.dump(analysis, f, indent=2, default=str)

    flagged_12mo = len(time_decay["older_than_12mo"])
    print(f"\n  Phase 2 analysis complete:")
    print(f"    Already classified archive: {len(already_archive)}")
    print(f"    Time decay candidates:      {len(td_ids)}")
    print(f"    Dedup candidates:           {len(dedup_ids)}")
    print(f"    Flagged for review (>12mo): {flagged_12mo}")
    print(f"    ────────────────────────────")
    print(f"    Total would archive:        {len(archive_ids)}")
    print(f"    Total would keep:           {len(keep_ids)}")
    print(f"\n    Output → {out_path}")

    return analysis


def phase2_preview(output_dir):
    """Print a human-readable approval summary from phase2_analysis.json."""
    analysis_path = output_dir / "phase2_analysis.json"
    if not analysis_path.exists():
        sys.exit(f"ERROR: {analysis_path} not found. Run phase2-analyse first.")

    with open(analysis_path) as f:
        analysis = json.load(f)

    acct = analysis.get("account", output_dir.name)
    summary = analysis["summary"]
    td = analysis["time_decay_candidates"]
    dedup = analysis["dedup_candidates"]

    print(f"\n  ╔══════════════════════════════════════════════╗")
    print(f"  ║  Phase 2 Preview — {acct:<25s} ║")
    print(f"  ╚══════════════════════════════════════════════╝")

    print(f"\n  Remaining before Phase 2:  {analysis['total_remaining']}")
    print(f"  Already classified archive: {summary['already_classified_archive']}")
    print(f"  Time-decay archives:        {summary['time_decay_archive']}")
    print(f"    - Notifications >7d:  {td['notifications_over_7d']}")
    print(f"    - Receipts >90d:      {td['receipts_over_90d']}")
    print(f"    - Security >30d:      {td['security_over_30d']}")
    print(f"    - Newsletters >14d:   {td['newsletters_over_14d']}")
    print(f"    - Older than 12mo:    {td['older_than_12mo']}")
    print(f"  Dedup archives:             {summary['dedup_archive']}")
    print(f"    - Burst groups:       {dedup['burst_groups']}")
    flagged = summary.get('flagged_for_review_12mo', 0)
    if flagged:
        print(f"  Flagged for review (>12mo):  {flagged} (not auto-archived)")
    print(f"  ────────────────────────────────────────────────")
    print(f"  Would archive:  {summary['total_would_archive']}")
    print(f"  Would keep:     {summary['total_would_keep']}")

    # Top 10 sender patterns being considered
    patterns = analysis.get("sender_patterns", [])
    # Sort by total messages descending
    top = sorted(patterns, key=lambda x: x["total"], reverse=True)[:10]
    if top:
        print(f"\n  Top 10 senders in remaining set:")
        for i, sp in enumerate(top, 1):
            top_pat = sp["patterns"][0]["pattern"] if sp["patterns"] else "—"
            print(f"    {i:2d}. {sp['sender']:<40s} ({sp['total']:>3d}) — \"{top_pat}\"")

    # Show dedup burst details
    if dedup["groups"]:
        print(f"\n  Dedup burst groups ({dedup['burst_groups']}):")
        for g in dedup["groups"][:10]:
            print(f"    - {g['sender']}: \"{g['pattern']}\" — {g['total_in_burst']} msgs, archive {len(g['archive_msg_ids'])}")

    # Categories being kept
    keep_cats = summary.get("keep_by_category", {})
    if keep_cats:
        print(f"\n  Emails being KEPT (by category):")
        for cat, count in sorted(keep_cats.items(), key=lambda x: -x[1]):
            print(f"    - {cat}: {count}")

    print(f"\n  Run 'phase2-archive --account {acct}' for dry run")
    print(f"  Run 'phase2-archive --account {acct} --execute' to archive")


def scan_inbox_uids_for_phase2(mail, target_msg_ids, messages_lookup):
    """
    Scan INBOX using UIDs and return UIDs whose messages match the target set.
    Matches by sender + subject + date since msg_ids are sequence numbers from
    the original scan and may have changed.
    """
    mail.select("INBOX", readonly=True)
    _, data = mail.uid("search", None, "ALL")
    all_uids = data[0].split() if data[0] else []

    if not all_uids:
        return []

    # Build a lookup set of (sender, normalised_subject) for target messages
    target_keys = set()
    for mid in target_msg_ids:
        msg = messages_lookup.get(mid)
        if msg:
            key = (msg["from_email"].lower(), _normalise_subject(msg["subject"]).lower())
            target_keys.add(key)

    matched_uids = []
    batch_size = 500
    for i in range(0, len(all_uids), batch_size):
        batch = all_uids[i:i + batch_size]
        uid_set = b",".join(batch)
        _, batch_data = mail.uid("fetch", uid_set, "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT)])")

        for item in batch_data:
            if item is None or not isinstance(item, tuple):
                continue
            resp_line = item[0].decode() if isinstance(item[0], bytes) else str(item[0])
            uid_val = None
            if "UID " in resp_line:
                uid_val = resp_line.split("UID ")[1].split(" ")[0].split(")")[0]
            if not uid_val:
                continue

            raw_header = item[1]
            try:
                msg = email.message_from_bytes(raw_header)
            except Exception:
                continue

            from_raw = decode_header_value(msg.get("From", ""))
            sender = get_sender_email(from_raw)
            subject = _normalise_subject(decode_header_value(msg.get("Subject", "")))
            key = (sender.lower(), subject.lower())

            if key in target_keys:
                matched_uids.append(uid_val)

        print(f"    Scanned {min(i + batch_size, len(all_uids))}/{len(all_uids)}, matched: {len(matched_uids)}")

    return matched_uids


def phase2_archive(mail, output_dir, dry_run=True, account=None):
    """
    Archive messages identified by phase2_analysis.json.
    Uses the same safe UID-based approach as Phase 1.
    """
    analysis_path = output_dir / "phase2_analysis.json"
    if not analysis_path.exists():
        sys.exit(f"ERROR: {analysis_path} not found. Run phase2-analyse first.")

    with open(analysis_path) as f:
        analysis = json.load(f)

    archive_msg_ids = set(analysis.get("archive_msg_ids", []))
    if not archive_msg_ids:
        print("  No messages to archive.")
        return 0

    # Build message lookup from classification/remaining data
    class_path = output_dir / "pass2_classification.json"
    remain_path = output_dir / "pass2_remaining.json"
    if class_path.exists():
        with open(class_path) as f:
            all_msgs = json.load(f)
    elif remain_path.exists():
        with open(remain_path) as f:
            all_msgs = json.load(f)
    else:
        sys.exit(f"ERROR: No pass2 data found in {output_dir}")

    messages_lookup = {m["msg_id"]: m for m in all_msgs}

    print(f"  Phase 2: targeting {len(archive_msg_ids)} messages for archive")
    print(f"  Scanning INBOX for matching messages...")

    matched_uids = scan_inbox_uids_for_phase2(mail, archive_msg_ids, messages_lookup)

    if not matched_uids:
        print("  No matching messages found in INBOX (may already be archived).")
        return 0

    if dry_run:
        print(f"\n  [DRY RUN] Would archive {len(matched_uids)} messages")
        print(f"  Run with --execute to perform the archive.")
        return 0

    # Archive using same approach as Phase 1
    gmail = is_gmail(account) if account else True
    pre_allmail_count = 0
    archive_folder = None
    batch_size = 200

    if gmail:
        mail.select('"[Gmail]/All Mail"', readonly=True)
        _, data = mail.search(None, "ALL")
        pre_allmail_count = len(data[0].split()) if data[0] else 0
    else:
        archive_folder = ensure_archive_folder(mail)
        if not archive_folder:
            print("    ERROR: Could not create Archive folder. Aborting.")
            return 0
        print(f"    Using folder '{archive_folder}' for archived messages")

    mail.select("INBOX")
    archived = 0

    for i in range(0, len(matched_uids), batch_size):
        batch = matched_uids[i:i + batch_size]
        uid_set = ",".join(batch)

        if not gmail:
            typ, _ = mail.uid("copy", uid_set, archive_folder)
            if typ != "OK":
                print(f"    ERROR: UID COPY failed for batch at offset {i}")
                continue

        typ, _ = mail.uid("store", uid_set, "+FLAGS", "\\Deleted")
        if typ != "OK":
            print(f"    ERROR: UID STORE failed for batch at offset {i}")
            continue

        archived += len(batch)
        if archived % 1000 == 0 or i + batch_size >= len(matched_uids):
            print(f"    Flagged: {archived}/{len(matched_uids)}")

    print("    Expunging...")
    mail.expunge()

    if not verify_archive_safety(mail, pre_allmail_count, account or {}):
        print("\n  WARNING: All Mail count decreased after archive!")
    else:
        print("    Safety check passed — All Mail count stable")

    print(f"    Archived: {archived}")
    return archived


# ── CLI entry point ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Inbox Zero — Gmail triage")
    parser.add_argument("command", choices=[
                            "pass1", "pass2", "archive", "status", "merge-rules", "monitor",
                            "phase2-analyse", "phase2-preview", "phase2-archive",
                        ],
                        help="Which step to run")
    parser.add_argument("--account", help="Account name from accounts.json")
    parser.add_argument("--all", action="store_true", help="Run for all accounts")
    parser.add_argument("--execute", action="store_true", help="Actually perform archive (default is dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes (default for archive)")
    parser.add_argument("--output-dir", help="Override output directory (default: triage_output/<account>)")
    parser.add_argument("--interval", type=int, default=3, help="Monitor refresh interval in seconds (default: 3)")

    args = parser.parse_args()
    accounts = load_accounts()

    if args.command == "merge-rules":
        merge_rules_command()
        return

    if args.command == "monitor":
        monitor_command(interval=args.interval)
        return

    # Determine which accounts to process
    if args.all:
        targets = accounts
    else:
        targets = [get_account(accounts, args.account)]

    for account in targets:
        if args.output_dir:
            output_dir = Path(args.output_dir)
            output_dir.mkdir(parents=True, exist_ok=True)
        else:
            output_dir = get_output_dir(account["name"])

        if args.command == "status":
            status_command(account)
            continue

        # Phase 2 analyse and preview don't need IMAP
        if args.command == "phase2-analyse":
            print(f"\n=== PHASE 2: Analyse — {account['name']} ===")
            phase2_analyse(output_dir)
            continue

        if args.command == "phase2-preview":
            phase2_preview(output_dir)
            continue

        mail = connect(account)

        try:
            if args.command == "phase2-archive":
                dry_run = not args.execute
                print(f"\n=== PHASE 2: Archive — {account['name']} ===")
                archived = phase2_archive(mail, output_dir, dry_run=dry_run, account=account)
                if not dry_run:
                    print(f"\n  Done. {archived} messages archived.")

            elif args.command == "pass1":
                print(f"\n=== PASS 1: Metadata scan — {account['name']} ===")
                cp_path = output_dir / "checkpoint_metadata.json"
                messages = fetch_metadata(mail, checkpoint_path=cp_path)

                shared = load_shared_rules()
                pass1_sender_analysis(messages, output_dir, shared_rules=shared)

                # Save full message list for pass2
                msg_path = output_dir / "all_messages.json"
                with open(msg_path, "w") as f:
                    json.dump(messages, f, indent=2, default=str)
                print(f"    Message list → {msg_path}")

            elif args.command == "pass2":
                rules_path = output_dir / "archive_rules.json"
                msg_path = output_dir / "all_messages.json"

                if not rules_path.exists():
                    sys.exit(f"ERROR: {rules_path} not found. Run pass1 first, then create archive_rules.json.")
                if not msg_path.exists():
                    sys.exit(f"ERROR: {msg_path} not found. Run pass1 first.")

                with open(rules_path) as f:
                    rules = json.load(f)
                with open(msg_path) as f:
                    messages = json.load(f)

                archive_senders = rules.get("archive_senders", [])
                # Also include shared rules
                shared = load_shared_rules()
                archive_senders += shared.get("archive_senders", [])
                archive_senders = list(set(s.lower() for s in archive_senders))

                print(f"\n=== PASS 2: Body analysis — {account['name']} ===")
                print(f"  {len(archive_senders)} senders marked for archive")
                pass2_body_analysis(mail, messages, archive_senders, output_dir)

            elif args.command == "archive":
                rules_path = output_dir / "archive_rules.json"

                if not rules_path.exists():
                    sys.exit(f"ERROR: {rules_path} not found.")

                with open(rules_path) as f:
                    rules = json.load(f)

                # Collect all senders to archive
                all_archive_senders = set(s.lower() for s in rules.get("archive_senders", []))

                # Add shared rules
                shared = load_shared_rules()
                all_archive_senders.update(s.lower() for s in shared.get("archive_senders", []))

                # Also add senders from body-classified "archive" messages
                class_path = output_dir / "pass2_classification.json"
                if class_path.exists():
                    with open(class_path) as f:
                        classifications = json.load(f)
                    for c in classifications:
                        if c.get("category") == "archive":
                            all_archive_senders.add(c["from_email"].lower())

                dry_run = not args.execute

                print(f"\n=== ARCHIVE — {account['name']} ===")
                print(f"  {len(all_archive_senders)} senders targeted")

                archived = archive_messages(mail, all_archive_senders, dry_run=dry_run, account=account)
                if not dry_run:
                    print(f"\n  Done. {archived} messages archived.")

        finally:
            safe_disconnect(mail)


if __name__ == "__main__":
    main()
