# Inbox Zero — Agent Handover

## Project

Multi-account email triage via IMAP. Single script `email_triage.py` with CLI commands for a two-phase workflow. Both phases are now complete across all accounts.

## Accounts (from accounts.json)

| Name | Email | IMAP |
|------|-------|------|
| chef | chefandrewisherwood@gmail.com | Gmail |
| bugle | andrew@bugle.agency | Gmail |
| traiteur | traiteurdelonnes@gmail.com | Gmail |
| yardsaleuk | yardsaleproductionsuk@gmail.com | Gmail |
| hellome | hello@andrewisherwood.me | Namecheap (mail.privateemail.com) |
| yardsale | andy@yardsaleproductions.com | Namecheap (mail.privateemail.com) |

**Important:** The `chef` account's output directory is `triage_output/chefandrewisherwood/` (legacy naming from before account was renamed). Use `--output-dir triage_output/chefandrewisherwood` when running phase2 commands for chef.

## Current State (as of 2026-02-15)

### Phase 1: COMPLETE for all accounts
~44,000+ emails archived across all accounts using sender-level rules.

### Phase 2: Pattern Refinement — COMPLETE for all accounts

| Account | Classified | Analysed | Archived | Phase 2 |
|---------|:-:|:-:|:-:|:-:|
| chef | 1,826 msgs | 591 archive, 1,235 keep | 41 archived | DONE |
| traiteur | 2,182 msgs | 392 archive, 1,790 keep | 511 archived | DONE |
| bugle | 2,472 msgs | 1,329 archive, 1,143 keep | 1,192 archived | DONE |
| hellome | 6,489 msgs | 4,074 archive, 2,415 keep | 4,218 archived | DONE |
| yardsale | 8,991 msgs | 6,475 archive, 2,516 keep | 6,871 archived | DONE |

**Total archived across both phases: ~57,000+ emails.**

### Classification approach

- chef/traiteur/bugle were classified manually via Claude conversation
- hellome was classified via `classify_hellome.py` (rule-based script)
- yardsale was classified via `classify_yardsale.py` (rule-based script)

**Classification rules (from inbox-zero-phase2.md):**
- Financial records always kept (bank statements, tax, invoices, HMRC)
- Personal correspondence always kept (real humans — family, friends, clients)
- School/Flora always kept
- Medical/ADHD records always kept
- Bias toward archiving for everything else

### Bug fix applied

`ensure_archive_folder()` in `email_triage.py` was failing to detect existing `Archive` folders on Namecheap servers when the folder name was unquoted in the IMAP LIST response. Fixed to match both quoted and unquoted folder names.

## CLI Commands

```bash
# Phase 1 (already done)
python3 email_triage.py pass1 --account <name>
python3 email_triage.py pass2 --account <name>
python3 email_triage.py archive --account <name>           # dry run
python3 email_triage.py archive --account <name> --execute  # live

# Phase 2 (complete)
python3 email_triage.py phase2-analyse --account <name>     # produces phase2_analysis.json
python3 email_triage.py phase2-preview --account <name>     # human-readable summary
python3 email_triage.py phase2-archive --account <name>     # dry run
python3 email_triage.py phase2-archive --account <name> --execute  # live

# For chef specifically (output dir mismatch):
python3 email_triage.py phase2-analyse --account chef --output-dir triage_output/chefandrewisherwood
python3 email_triage.py phase2-preview --account chef --output-dir triage_output/chefandrewisherwood
python3 email_triage.py phase2-archive --account chef --output-dir triage_output/chefandrewisherwood

# Utilities
python3 email_triage.py status --account <name>
python3 email_triage.py monitor                             # live dashboard
python3 email_triage.py merge-rules                         # cross-account shared rules
```

## Phase 2 Analysis Logic

The `phase2-analyse` command applies three refinement layers:

1. **Subject pattern clusters** — Groups messages by sender, clusters subjects by first-4-word prefix
2. **Time decay** — Auto-archives:
   - Notifications >7 days old
   - Receipts >90 days (non-financial)
   - Security alerts >30 days
   - Newsletters >14 days
   - Messages >12 months are **flagged for review only** (NOT auto-archived) to protect personal correspondence
3. **Deduplication** — Same sender, 5+ similar subjects within 24h window → keep newest, archive rest

Messages classified as `urgent` or `action_needed` are never touched by time decay.

## Next Steps

1. **Set up forwarding** from all accounts to `hello@andrewisherwood.com`
2. **Adapt the script** to run as a cron job on new mail only
3. **Morning digest** — what arrived, what was archived, what needs attention
4. **Auto-unsubscribe** via `List-Unsubscribe` header for confirmed noise senders

See `inbox-zero-phase2.md` for full details on post-inbox-zero plans.

## Key Files

- `email_triage.py` — all logic, single file
- `accounts.json` — account credentials (sensitive, not committed)
- `shared_rules.json` — cross-account archive senders
- `classify_hellome.py` — rule-based classifier for hellome account
- `classify_yardsale.py` — rule-based classifier for yardsale account
- `triage_output/<account>/` — per-account data:
  - `pass1_summary.json`, `pass1_sender_report.csv`
  - `archive_rules.json` — Phase 1 sender rules
  - `all_messages.json` — full metadata from pass1
  - `pass2_remaining.json` — messages needing body analysis
  - `pass2_classification.json` — classified messages
  - `phase2_analysis.json` — Phase 2 analysis output
- `project-inbox-zero.md` — original project spec
- `inbox-zero-phase2.md` — Phase 2 design doc

## Safety Model

- All archive operations are dry-run by default, require `--execute`
- Gmail: removes INBOX label only (stays in All Mail)
- Non-Gmail (Namecheap): COPY to Archive folder, then DELETE
- Post-archive safety check verifies All Mail count hasn't decreased
- UID-based operations (stable across expunges)
