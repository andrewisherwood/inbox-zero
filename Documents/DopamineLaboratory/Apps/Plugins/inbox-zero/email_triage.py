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
import sys
import json
import csv
import argparse
from datetime import datetime, timezone
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


def connect(account):
    """Connect and authenticate to Gmail IMAP."""
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(account["email"], account["app_password"])
        return mail
    except imaplib.IMAP4.error as e:
        sys.exit(f"ERROR: IMAP login failed for {account['email']}: {e}")


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
    print(f"  Fetching metadata for {len(remaining_ids)} messages ({len(fetched_ids)} cached, {total} total)...")

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
    50 messages per FETCH = ~50x fewer round trips than one-at-a-time.
    """
    results = {}

    if checkpoint_path:
        cp = load_checkpoint(checkpoint_path)
        if cp and "bodies" in cp:
            results = cp["bodies"]
            msg_ids = [mid for mid in msg_ids if mid not in results]
            print(f"    Resuming: {len(results)} bodies cached, {len(msg_ids)} remaining")

    total = len(msg_ids) + len(results)

    for i in range(0, len(msg_ids), batch_size):
        batch = msg_ids[i:i + batch_size]
        id_set = ",".join(batch)

        try:
            _, batch_data = mail.fetch(id_set.encode(), "(BODY.PEEK[TEXT])")
        except Exception as e:
            print(f"    Warning: batch body fetch failed at offset {i}: {e}")
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
        print(f"    Bodies: {done}/{total}")

        # Checkpoint every 5 batches
        if checkpoint_path and (i // batch_size) % 5 == 4:
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


def verify_archive_safety(mail, sample_id):
    """After archiving from INBOX, check the message still exists in All Mail."""
    try:
        mail.select("[Gmail]/All Mail", readonly=True)
        _, data = mail.search(None, f"{sample_id}")
        mail.select("INBOX")  # switch back
        return data[0] and len(data[0].split()) > 0
    except Exception:
        mail.select("INBOX")
        return False


def archive_messages(mail, msg_ids, dry_run=True, batch_size=100):
    """
    Archive messages from INBOX.
    Gmail: +FLAGS \\Deleted + EXPUNGE on INBOX = remove INBOX label.
    Messages stay in [Gmail]/All Mail.
    """
    if not msg_ids:
        print("  No messages to archive.")
        return 0

    if dry_run:
        print(f"\n  [DRY RUN] Would archive {len(msg_ids)} messages")
        print(f"  Run with --execute to perform the archive.")
        return 0

    mail.select("INBOX")
    archived = 0

    for i in range(0, len(msg_ids), batch_size):
        batch = msg_ids[i:i + batch_size]
        id_set = ",".join(batch)

        typ, _ = mail.store(id_set, "+FLAGS", "\\Deleted")
        if typ != "OK":
            print(f"    ERROR: STORE failed for batch at offset {i}")
            continue

        mail.expunge()
        archived += len(batch)

        # Safety check after first batch
        if i == 0:
            if not verify_archive_safety(mail, batch[0]):
                print("\n  SAFETY STOP: Archived message not found in All Mail!")
                print("  Check Gmail Settings > IMAP:")
                print("    - Auto-Expunge: ON")
                print("    - When deleted: 'Archive the message' (default)")
                return archived
            print("    Safety check passed — archived messages confirmed in All Mail")

        print(f"    Archived: {archived}/{len(msg_ids)}")

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


# ── CLI entry point ─────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(description="Inbox Zero — Gmail triage")
    parser.add_argument("command", choices=["pass1", "pass2", "archive", "status", "merge-rules"],
                        help="Which step to run")
    parser.add_argument("--account", help="Account name from accounts.json")
    parser.add_argument("--all", action="store_true", help="Run for all accounts")
    parser.add_argument("--execute", action="store_true", help="Actually perform archive (default is dry run)")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no changes (default for archive)")

    args = parser.parse_args()
    accounts = load_accounts()

    if args.command == "merge-rules":
        merge_rules_command()
        return

    # Determine which accounts to process
    if args.all:
        targets = accounts
    else:
        targets = [get_account(accounts, args.account)]

    for account in targets:
        output_dir = get_output_dir(account["name"])

        if args.command == "status":
            status_command(account)
            continue

        mail = connect(account)

        try:
            if args.command == "pass1":
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
                msg_path = output_dir / "all_messages.json"

                if not rules_path.exists():
                    sys.exit(f"ERROR: {rules_path} not found.")
                if not msg_path.exists():
                    sys.exit(f"ERROR: {msg_path} not found.")

                with open(rules_path) as f:
                    rules = json.load(f)
                with open(msg_path) as f:
                    messages = json.load(f)

                # Collect all message IDs to archive
                archive_senders = set(s.lower() for s in rules.get("archive_senders", []))

                # Add shared rules
                shared = load_shared_rules()
                archive_senders.update(s.lower() for s in shared.get("archive_senders", []))

                sender_archive_ids = [m["msg_id"] for m in messages if m["from_email"] in archive_senders]

                # Also archive messages classified as "archive" in pass2
                class_path = output_dir / "pass2_classification.json"
                body_archive_ids = []
                if class_path.exists():
                    with open(class_path) as f:
                        classifications = json.load(f)
                    body_archive_ids = [c["msg_id"] for c in classifications if c.get("category") == "archive"]

                all_archive_ids = list(set(sender_archive_ids + body_archive_ids))
                dry_run = not args.execute

                print(f"\n=== ARCHIVE — {account['name']} ===")
                print(f"  Sender-based: {len(sender_archive_ids)} messages")
                print(f"  Body-based:   {len(body_archive_ids)} messages")
                print(f"  Total:        {len(all_archive_ids)} messages")

                archived = archive_messages(mail, all_archive_ids, dry_run=dry_run)
                if not dry_run:
                    print(f"\n  Done. {archived} messages archived.")

        finally:
            safe_disconnect(mail)


if __name__ == "__main__":
    main()
