# Project Inbox Zero — CC Email Triage

## Overview

Autonomous email triage for Gmail accounts with thousands of unread messages. CC makes confident decisions and only surfaces what needs a human. You review what CC kept, not what it archived.

Supports multiple accounts via `accounts.json`. Cross-account shared rules mean newsletters triaged on account #1 are auto-archived on accounts #2–5.

---

## Prerequisites

### 1. Gmail App Password (per account)

Google blocks basic IMAP auth. You need an App Password:

1. Go to https://myaccount.google.com/security
2. Ensure 2-Step Verification is ON
3. Search for "App Passwords" in the security settings
4. Generate one — select "Mail" as the app
5. Copy the 16-character password

### 2. Gmail IMAP Settings (verify once per account)

Go to Gmail Settings > Forwarding and POP/IMAP and confirm:
- IMAP Access: **Enabled**
- Auto-Expunge: **ON** (default)
- When a message is marked as deleted: **Archive the message** (default)

These are the defaults — just verify they haven't been changed. If "immediately delete forever" is selected, the archive command would permanently delete messages.

### 3. Python Dependencies

```bash
pip install -r requirements.txt
```

### 4. Account Setup

**Single account** — create `.env` in the project root:

```
GMAIL_ADDRESS=your.email@gmail.com
GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
```

**Multiple accounts** — create `accounts.json`:

```json
{
  "accounts": [
    {
      "name": "chef",
      "email": "chefandrewisherwood@gmail.com",
      "app_password": "xxxx xxxx xxxx xxxx"
    },
    {
      "name": "work",
      "email": "andrew@example.com",
      "app_password": "xxxx xxxx xxxx xxxx"
    }
  ]
}
```

Both files are gitignored. DO NOT commit them.

---

## CLI Usage

```bash
python email_triage.py pass1 [--account NAME | --all]
python email_triage.py pass2 [--account NAME | --all]
python email_triage.py archive [--account NAME | --all] [--dry-run | --execute]
python email_triage.py status [--account NAME | --all]
python email_triage.py merge-rules
```

- With no flags, uses the first (or only) account
- `--account chef` targets a specific account
- `--all` runs sequentially for every account
- Archive is always dry-run unless you pass `--execute`

---

## CC Workflow

Open CC in the project directory. Give it the following prompt:

---

### Prompt for CC

```
I need you to triage my Gmail inbox. There are thousands of unread messages. We do this in 2 passes. You make confident decisions autonomously. I only review what you KEPT, not what you archived.

## Pass 1: Sender Analysis

Run `python email_triage.py pass1 --account <NAME>`

This scans INBOX metadata only (fast, no bodies). It produces:
- `triage_output/<account>/pass1_summary.json` — overview stats
- `triage_output/<account>/pass1_sender_report.csv` — every sender ranked by frequency

Read both files. Then create `triage_output/<account>/archive_rules.json`:

{
  "archive_senders": ["sender1@example.com", "sender2@example.com"],
  "archive_reasons": {
    "sender1@example.com": "Marketing newsletter, 200+ emails, never replied",
    "sender2@example.com": "Automated shipping notifications"
  },
  "keep_senders": ["important@example.com"],
  "keep_reasons": {
    "important@example.com": "Looks like personal correspondence"
  },
  "unsure_senders": ["maybe@example.com"],
  "unsure_reasons": {
    "maybe@example.com": "Only 3 emails, unclear if important"
  }
}

Rules for auto-archive (be aggressive):
- Marketing newsletters and promotions
- Automated notifications (shipping, delivery, order confirmations older than 90 days)
- Social media notifications (Facebook, Twitter, LinkedIn, Instagram)
- App notifications (Uber, Deliveroo, etc.)
- Subscription receipts and billing confirmations older than 12 months
- Any sender with 20+ emails where subjects are clearly automated/templated
- Password reset emails older than 30 days
- Forum/community digest emails

Rules for auto-keep:
- Anything that looks like personal correspondence (real human writing to Andy)
- Anything from government (HMRC, council, NHS)
- Anything from schools (Flora-related)
- Anything financial that might be needed for records (tax, invoices, contracts)
- Anything from family (Lily, parents, relatives)

Show me ONLY:
- How many senders marked for archive and how many emails that covers
- How many senders kept
- How many unsure — show the unsure list so I can make quick calls
- Any senders worth adding to shared_rules.json for future accounts

Wait for my approval before moving to Pass 2.

## Pass 2: Body Analysis + Archive

After I approve the archive rules, run `python email_triage.py pass2 --account <NAME>`

This batch-fetches body previews ONLY for messages not covered by archive rules (much smaller set). Read `triage_output/<account>/pass2_remaining.json` and classify each message:

- **urgent** — time-sensitive, overdue, or critical
- **action_needed** — requires Andy to reply, pay, or decide
- **reference** — important document, receipt, or info to keep but no action needed
- **archive** — noise not caught by sender rules

Write `triage_output/<account>/pass2_classification.json` with the results. Each entry needs a "category" field.

Show me:
- The full "urgent" list
- The full "action_needed" list
- Count of "reference" items (I'll browse later)
- Count of additional "archive" items

When I confirm, run:
  python email_triage.py archive --account <NAME>          # dry run first
  python email_triage.py archive --account <NAME> --execute # then for real

## After Each Account

Run `python email_triage.py merge-rules` to promote common senders to shared_rules.json. These are auto-applied on the next account, speeding up triage.
```

---

## Safety Notes

- Pass 1 is **read-only**. Nothing gets moved or deleted.
- Pass 2 is **read-only**. Nothing gets moved or deleted.
- The `archive` command is the only action that modifies your inbox. It defaults to **dry run** — you must explicitly pass `--execute`.
- Gmail archive removes the INBOX label. Messages stay in All Mail. Nothing is deleted.
- The script verifies archive safety after the first batch — if a message disappears from All Mail, it halts immediately.
- If anything goes wrong, everything is still in All Mail.
- Both `.env` and `accounts.json` are gitignored. Don't commit credentials.

## After Triage

Once the inbox is clean:
- Set up forwarding to `hello@andrewisherwood.com` if not already done
- Move on to the next account
- Schedule a monthly 20-minute session to keep it clean
- If monthly sessions feel like enough, you never need to build V1
