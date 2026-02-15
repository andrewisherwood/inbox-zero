# Inbox Zero — Phase 2: Pattern Refinement

## Context

Phase 1 archived ~44,000 emails using sender-level rules. ~3,500 emails remain across 4 accounts. These survived because their senders have a mix of signal and noise — you can't blanket archive them. Now we refine with subject pattern matching, time-based decay, and deduplication.

The goal is inbox zero. Not inbox 3,500.

## The Three Refinement Layers

### Layer 1: Sender + Subject Pattern Rules

Stop thinking in senders. Start thinking in patterns. Most remaining senders have useful AND useless emails:

**Examples:**
- GitHub: "Personal access token was created" → archive. "Security alert" → keep.
- Google: "Security alert: new sign-in" → keep one, archive duplicates. "Storage almost full" → archive.
- Apple: "Your receipt" → keep for records. "New features in iOS" → archive.
- Banks/utilities: "Your statement is ready" → keep. "Go paperless!" → archive.
- School: Anything from Flora's school → keep. PTA fundraising spam → archive.

For each sender remaining in the inbox, classify their emails by subject pattern, not just sender name.

### Layer 2: Time-Based Decay

Informational emails have a shelf life. Apply these rules:

- **Notifications older than 7 days** that haven't been replied to or starred → archive
- **Receipts and confirmations older than 90 days** → archive (unless financial — keep those)
- **Security alerts older than 30 days** → archive (the moment has passed)
- **Newsletter/digest content older than 14 days** → archive (you're never going back to read it)
- **Anything older than 12 months** that survived Phase 1 → flag for review but bias toward archive

### Layer 3: Deduplication

Notification storms create clutter even from important senders:

- If the same sender sent **5+ emails with similar subjects within 24 hours**, keep only the most recent, archive the rest
- "Similar subjects" means: same prefix, same template with different values (e.g. "Your order #1234 shipped" and "Your order #5678 shipped")
- GitHub notifications, CI/CD alerts, social media digests, and transactional email are the worst offenders

## Process

### Step 1: Analyse What Remains

For each account, scan the remaining inbox messages. Build a report:

```
triage_output/{account}/phase2_analysis.json
```

Structure:
```json
{
  "total_remaining": 748,
  "sender_patterns": [
    {
      "sender": "notifications@github.com",
      "total": 47,
      "patterns": [
        {
          "pattern": "Personal access token",
          "count": 12,
          "oldest": "2026-01-15",
          "newest": "2026-02-14",
          "recommendation": "archive_all",
          "reason": "Informational notifications about token lifecycle. No action needed."
        },
        {
          "pattern": "Security alert",
          "count": 3,
          "oldest": "2025-11-02",
          "newest": "2026-02-10",
          "recommendation": "keep_newest_archive_rest",
          "reason": "Security alerts worth a glance but only the most recent matters."
        }
      ]
    }
  ],
  "time_decay_candidates": {
    "notifications_over_7d": 234,
    "receipts_over_90d": 56,
    "security_over_30d": 12,
    "newsletters_over_14d": 89
  },
  "dedup_candidates": {
    "burst_groups": 15,
    "total_duplicates": 67
  }
}
```

### Step 2: Build Refined Rules

Create pattern-based rules:

```
triage_output/{account}/phase2_rules.json
```

Structure:
```json
{
  "pattern_rules": [
    {
      "sender_contains": "github.com",
      "subject_contains": ["Personal access token", "dependabot", "Actions workflow run"],
      "action": "archive",
      "reason": "Automated GitHub notifications — informational only"
    },
    {
      "sender_contains": "github.com",
      "subject_contains": ["Security alert", "billing", "access revoked"],
      "action": "keep",
      "reason": "Security and billing — needs attention"
    }
  ],
  "time_decay_rules": [
    {
      "category": "notification",
      "older_than_days": 7,
      "no_reply": true,
      "action": "archive"
    },
    {
      "category": "receipt",
      "older_than_days": 90,
      "not_financial": true,
      "action": "archive"
    }
  ],
  "dedup_rules": [
    {
      "sender_contains": "github.com",
      "similar_subjects_within_hours": 24,
      "keep": "newest",
      "archive": "rest"
    }
  ]
}
```

### Step 3: Show Me the Plan

Before archiving anything, show me a summary per account:

```
Account: chef
Remaining before Phase 2: 748
Pattern-based archives: 312
Time-decay archives: 145
Dedup archives: 34
────────────────────────
Would archive: 491
Would keep: 257

Top 10 patterns being archived:
1. GitHub notifications (47) — token lifecycle, CI runs, dependabot
2. Google "Security alert: new sign-in" older than 30d (23)
3. Apple marketing emails (18)
...

Emails being KEPT (by category):
- Personal correspondence: 89
- Financial/tax records: 45
- School/Flora: 34
- Government/HMRC: 12
- Active subscriptions: 28
- Recent notifications (<7d): 49
```

**Wait for my approval before archiving.**

I will either say:
- "Go" — execute all
- "Adjust X" — change specific rules before executing
- "Show me the [category]" — drill into a specific group before deciding

### Step 4: Execute & Report

After approval, archive in the same safe way as Phase 1:
- Remove from INBOX only (stays in All Mail)
- UID-based operations
- Safety check: All Mail count stable after each batch
- Final report with counts

### Step 5: Update Shared Rules

After all accounts are processed, update `shared_rules.json` with the refined pattern rules. These become the baseline for the ongoing cron job later — new mail gets classified against these patterns automatically.

## Important Notes

- **Bias toward archiving.** If in doubt, archive. Everything stays in All Mail and is searchable. An empty inbox with searchable archives is better than a full inbox you never look at.
- **Financial records always kept.** Bank statements, tax correspondence, invoices, HMRC, accountant emails — never archive these regardless of age.
- **Personal correspondence always kept.** Real humans writing to Andy — family, friends, clients — never archive.
- **School always kept.** Anything related to Flora's school, activities, assessments — never archive.
- **Medical/ADHD records always kept.** Any health-related correspondence — never archive.
- **The unread status doesn't matter.** An unread email from 2024 is not more important than a read email from yesterday. Unread ≠ needs action.

## After Inbox Zero

Once we hit zero (or close to it), the next phase is:
1. Set up forwarding from all accounts to `hello@andrewisherwood.com`
2. Adapt the script to run as a cron job on new mail only
3. Morning digest: what arrived, what was archived, what needs you
4. Auto-unsubscribe via `List-Unsubscribe` header for confirmed noise senders

But that's after zero. One thing at a time.
