# Inbox Zero — Agent Handover

## Project

Multi-account email triage via IMAP. Single script `email_triage.py` with CLI commands for a two-phase workflow: Phase 1 (sender-level bulk archive) is complete. Phase 2 (pattern refinement) is in progress.

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

### Phase 2: Pattern Refinement — IN PROGRESS

| Account | pass2_remaining | pass2_classification | phase2_analysis | Next Step |
|---------|:-:|:-:|:-:|-----------|
| chef | 1,826 msgs | Done | Done (591 archive, 1,235 keep) | User reviews preview, then `phase2-archive` |
| traiteur | 2,182 msgs | Done | Done (392 archive, 1,790 keep) | User reviews preview, then `phase2-archive` |
| bugle | 2,472 msgs | Done | Done (1,329 archive, 1,143 keep) | User reviews preview, then `phase2-archive` |
| hellome | 6,489 msgs | **MISSING** | Not yet | Needs CC-assisted classification first |
| yardsale | 8,991 msgs | **MISSING** | Not yet | Needs CC-assisted classification first |

### What "CC-assisted classification" means

The `pass2_remaining.json` files contain messages with body previews. These need to be classified into categories:
- `archive` — safe to archive
- `reference` — keep (financial, property, childcare, government records)
- `action_needed` — needs user attention
- `urgent` — immediate attention

This was done manually via Claude for chef/traiteur/bugle. The output is `pass2_classification.json` — same structure as `pass2_remaining.json` but with `category` and `reason` fields added to each message.

**Classification rules (from inbox-zero-phase2.md):**
- Financial records always kept (bank statements, tax, invoices, HMRC)
- Personal correspondence always kept (real humans — family, friends, clients)
- School/Flora always kept
- Medical/ADHD records always kept
- Bias toward archiving for everything else

## CLI Commands

```bash
# Phase 1 (already done)
python3 email_triage.py pass1 --account <name>
python3 email_triage.py pass2 --account <name>
python3 email_triage.py archive --account <name>           # dry run
python3 email_triage.py archive --account <name> --execute  # live

# Phase 2 (current work)
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

## Uncommitted Changes

`email_triage.py` has significant uncommitted changes — the entire Phase 2 implementation (~250 new lines of functions + CLI wiring). Should be committed when the user is ready.

## Next Steps (in order)

1. **User reviews phase2 previews** for chef, traiteur, bugle — approves or adjusts
2. **Run phase2-archive** on approved accounts (dry run first, then --execute)
3. **Classify hellome** — 6,489 messages in `pass2_remaining.json` need CC-assisted classification → produce `pass2_classification.json`
4. **Classify yardsale** — 8,991 messages same treatment
5. **Run phase2 on hellome + yardsale** once classified
6. **After inbox zero** — forwarding setup, cron job, morning digest (see inbox-zero-phase2.md)

## Key Files

- `email_triage.py` — all logic, single file
- `accounts.json` — account credentials (sensitive, not committed)
- `shared_rules.json` — cross-account archive senders
- `triage_output/<account>/` — per-account data:
  - `pass1_summary.json`, `pass1_sender_report.csv`
  - `archive_rules.json` — Phase 1 sender rules
  - `all_messages.json` — full metadata from pass1
  - `pass2_remaining.json` — messages needing body analysis
  - `pass2_classification.json` — CC-classified messages
  - `phase2_analysis.json` — Phase 2 analysis output
- `project-inbox-zero.md` — original project spec
- `inbox-zero-phase2.md` — Phase 2 design doc

## Safety Model

- All archive operations are dry-run by default, require `--execute`
- Gmail: removes INBOX label only (stays in All Mail)
- Non-Gmail (Namecheap): COPY to Archive folder, then DELETE
- Post-archive safety check verifies All Mail count hasn't decreased
- UID-based operations (stable across expunges)
