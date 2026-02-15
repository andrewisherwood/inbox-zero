#!/usr/bin/env python3
"""Classify yardsale pass2_remaining.json messages into categories.

This is a business account (andy@yardsaleproductions.com) — Yardsale Productions.
Heavy Upwork, hosting, and accounting traffic.
"""

import json
import re
from collections import Counter

INPUT = "triage_output/yardsale/pass2_remaining.json"
OUTPUT = "triage_output/yardsale/pass2_classification.json"

# ── KEEP: Family / Personal ──────────────────────────────────────────────────
PERSONAL_SENDERS = {
    "isherwoodsimon@gmail.com",          # Simon Isherwood — family
    "isherwood_j@hotmail.com",           # James Isherwood — family
    "apisherwood@gmail.com",             # Anne Isherwood — family
    "chefandrewisherwood@gmail.com",     # Andy's personal email
    "hello@andrewisherwood.me",          # Andy's other email
    "andy@yardsaleproductions.com",      # Self (sent items in inbox)
    "simon@isherwood-online.de",         # Simon Work
    "djlewis.crichton2@virginmedia.co.uk",  # Personal contact
}

# ── KEEP: Financial / Accounting / Tax ────────────────────────────────────────
FINANCIAL_SENDERS = {
    # HMRC / Government
    "no.reply@advice.hmrc.gov.uk",
    "kcmt.admin@notifications.hmrc.gov.uk",
    "noreply@tax.service.gov.uk",
    "noreply@confirmation.tax.service.gov.uk",
    "no-reply@access.service.gov.uk",
    # Companies House
    "ereminders@companieshouse.gov.uk",
    "web-filing@companieshouse.gov.uk",
    "webfiling@companieshouse.gov.uk",
    "noreply@companieshouse.gov.uk",
    "enquiries@companieshouse.gov.uk",
    "companies.house.notifications@notifications.service.gov.uk",
    "companies.house@notifications.service.gov.uk",
    # Accountancy
    "info@theaccountancy.co.uk",
    "reminders@theaccountancy.co.uk",
    "sales@theaccountancy.co.uk",
    "payroll@theaccountancy.co.uk",
    "erin@theaccountancy.co.uk",
    "ellie@theaccountancy.co.uk",
    "sarah@theaccountancy.co.uk",
    "jessica@theaccountancy.co.uk",
    "kieran@theaccountancy.co.uk",
    "aimee@theaccountancy.co.uk",
    "charlotte@theaccountancyspace.co.uk",
    "support@southsideaccountants.co.uk",
    "echosign@echosign.com",             # Southside via DocuSign
    # Xero / QuickBooks / Pandle
    "noreply@send.xero.com",
    "noreply@post.xero.com",
    "billing@xero.com",
    "security@post.xero.com",
    "subscription.notifications@post.xero.com",
    "messaging-service@post.xero.com",
    "quickbooks@notification.intuit.com",
    "intuit@notifications.intuit.com",
    "intuit@eq.intuit.co.uk",
    "liam@pandle.com",
    # Wise / TransferWise
    "noreply@wise.com",
    "noreply@transferwise.com",
    "info@transferwise.com",
    "noreply@info.wise.com",
    "reply@support.wise.com",
    "hello@transferwise.com",
    # PayPal
    "service@paypal.co.uk",
    "paypal@mail.paypal.co.uk",
    "paypal@emails.paypal.com",
    "paypal@mail.paypal.com",
    # Stripe
    "support@stripe.com",
    # Banks
    "noreply@metrobank.plc.uk",
    "noreply@barclayspartnerfinance.com",
    # Apple billing
    "do_not_reply@email.apple.com",
    "no_reply@email.apple.com",
    "emea_invoicing@email.apple.com",
    # Virgin Media Business billing
    "mybill@virginmediabusiness.co.uk",
    # Other billing
    "billing@mailgun.net",
    "billing@liquidweb.com",
    "payments-noreply@google.com",
    # Mailgun billing
    "billing@xero.com",
}

# ── KEEP: Clients / Key work contacts ────────────────────────────────────────
CLIENT_SENDERS = {
    # Dorian Fund / O'Brian Woods — major client
    "owoods@dorianfund.com",
    "support@dorianway.com",
    "danielle@dorianway.com",
    "vadaniellenelson@gmail.com",        # Danielle Nelson personal
    # NRI Digital / Verdict — client
    "joe.roberts@verdict.co.uk",
    "tom.mccormick@nridigital.com",
    "creditcontrol@nridigital.com",
    "sop@nridigital.com",
    "sop@verdict.co.uk",
    "reports@nridigital.com",
    "nick.midgley@uk.timetric.com",
    "syed.zainulabeddin@verdict.co.uk",
    # GlobalData — client
    "anirudh.singh@globaldata.com",
    "melissa.parkinson@globaldata.com",
    "ashley.mcpherson@globaldata.com",
    "melissa.parkinson@compelo.com",
    "fraser.miller@globaldata.com",
    "noorie.banu@globaldata.com",
    "creditcontrol@globaldata.com",
    # Setform — client
    "cflaxman@setform.com",
    "lsmyth@setform.com",
    "jabey@setform.com",
    "lgilroy@setform.com",
    # Brandspeak — client
    "jeremy@brandspeak.co.uk",
    # APC Pure — client
    "info@apcpure.com",
    # Brad Thomas / Origin Storage — work contact
    "bradt@originstorage.com",
    # Daniel Huenebeck — key work contact
    "daniel@daniel-huenebeck.ch",
    # Michel Isoz / Nasaco — work contact
    "isoz@nasaco.ch",
    # Matteo Bianda — work contact
    "matteo.bianda@positioner.com",
    # Edward Banham-Hall — work contact
    "e.banhamhall@gmail.com",
    # Adam — work contact
    "adam@linnell.org",
    # Satish / Rel Studios — contractor
    "relstudiosnx@gmail.com",
    # Patrick Chan — work contact
    "patrickchanmed@gmail.com",
    # Enver / TekCabin — work contact
    "enver@tekcabin.com",
    # Access CM / Chloe Parker — work contact
    "collect@accesscm.co.uk",
    # Luna Creative — work contact
    "emma@weareluna.co.uk",
    # Sophie Larsmon — work contact
    "sophielarsmon@googlemail.com",
    # Kevin Cabacis @ Virgin Media — account contact
    "kevin.cabacis@virginmedia.co.uk",
    # TWM Solicitors
    "aasima.riaz-foster@twmsolicitors.com",
    # Karen Kilburn — business contact
    "karen@approvedbusiness.co.uk",
    # Thomas Brooks
    "thomas.brooks@hbxl.co.uk",
    # Tim Skeffington — work contact
    "tim.skeffington@savills.com",
    # AGA Electronics
    "agaelectronicsltd@gmail.com",
    # Stuart Logan
    "reply.6f46666c586d56325a774e34416a3d3d@mail.twinehq.com",
}

# ── KEEP: Upwork room messages (client conversations) ────────────────────────
# These are actual work conversations — kept as business records.
# We match all room_*@upwork.com addresses.

# ── KEEP: Hosting / Infrastructure (account & billing) ────────────────────────
HOSTING_KEEP_SENDERS = {
    "support@liquidweb.com",
    "noreply@liquidweb.com",
    "support@namecheap.com",
    "reminder@nominet.org.uk",           # Domain renewals
}

# ── ARCHIVE: Notifications / Marketing / Noise ───────────────────────────────
ARCHIVE_SENDERS = {
    # Upwork notifications (not room messages)
    "donotreply@upwork.com",
    "support@upwork.com",
    "support@upwork.zendesk.com",
    "accountsecurity@upwork.com",
    # Uptime Robot
    "alert@uptimerobot.com",
    # Google notifications
    "domains-noreply@google.com",
    "sc-noreply@google.com",
    "googleplay-noreply@google.com",
    "analytics-noreply@google.com",
    "no-reply@accounts.google.com",
    "businessprofile-noreply@google.com",
    "googlemybusiness-noreply@google.com",
    "optimize-noreply@google.com",
    "noreply-photos@google.com",
    "google-maps-noreply@google.com",
    "gsuite-noreply@google.com",
    "ads-account-noreply@google.com",
    "analytics-research-noreply@google.com",
    "noreply-google@google.com",
    "ads-noreply@google.com",
    "adwords-noreply@google.com",
    # SiteGround
    "noreply@siteground.com",
    # DigitalOcean
    "support@digitalocean.com",
    "no-reply@digitalocean.com",
    "no-reply@referrals.digitalocean.com",
    "support@support.digitalocean.com",
    "support@info.digitalocean.com",
    # Squarespace
    "no-reply@squarespace.com",
    # Instagram / Facebook / Social
    "no-reply@mail.instagram.com",
    "security@mail.instagram.com",
    "notification@facebookmail.com",
    "security@facebookmail.com",
    "verify@twitter.com",
    "noreply@discordapp.com",
    "no-reply@notifications.skype.com",
    # SproutVideo
    "support@sproutvideo.com",
    # GitHub notifications
    "notifications@github.com",
    "noreply@github.com",
    # Cloudflare
    "noreply@notify.cloudflare.com",
    "no-reply@notify.cloudflare.com",
    # giffgaff
    "no_reply@giffgaff.com",
    # MyTradeSite
    "noreply@mytradesite.co.uk",
    # WHMCS
    "noreply@whmcs.com",
    # 1Password
    "hello@1password.com",
    "support@1password.com",
    # Virgin Media marketing
    "email@em.virginmediabusiness.co.uk",
    # Smash Balloon
    "support@smashballoon.com",
    # ShapedPlugin
    "support@shapedplugin.com",
    # Freepik / Flaticon
    "info@freepik-mail.com",
    # Sentry
    "noreply@md.getsentry.com",
    # Adobe
    "message@adobe.com",
    "storemanager@adobe.com",
    "applesupport@email.apple.com",
    "mail@mail.adobe.com",
    # Photoshelter
    "do-not-reply@photoshelter.com",
    # Amazon
    "shipment-tracking@amazon.co.uk",
    "auto-confirm@amazon.co.uk",
    "account-update@amazon.co.uk",
    "digital-no-reply@amazon.co.uk",
    "no-reply-aws@amazon.com",
    # LinkedIn
    "jobalerts-noreply@linkedin.com",
    "inmail-hit-reply@linkedin.com",
    "hit-reply@linkedin.com",
    # OnePlus
    "orders-noreply@oneplus.net",
    "account@oneplus.net",
    # Vivino
    "uk.orders@vivino.com",
    # DPD
    "yourdelivery@dpd.co.uk",
    "yourorder@dpd.co.uk",
    # Bucket.io
    "support@bucket.io",
    "support@bucketiomail.com",
    # SSL / hosting noise
    "noreply@positivessl.com",
    "sales@gogetssl.com",
    # Mailgun
    "updates@mailgun.com",
    # Anima
    "anima.team@animaapp.com",
    # Eventbrite
    "donotreply@eventbrite.com",
    # Vistaprint
    "vistaprint@tm.vistaprint.co.uk",
    # Asana
    "no-reply@asana.com",
    "reply-e673a950c8445493cb9d19ebf14c3bfa@asana.com",
    "noreply@qemailserver.com",
    # Microsoft Ads
    "media@bingads.com",
    # Dropbox
    "no-reply@dropbox.com",
    # BrandCrowd
    "customersuccess@brandcrowd.com",
    "logosaved@brandcrowd.com",
    # Webflow
    "contact@hello.webflow.com",
    # Figma
    "support@figma.com",
    # WP Rocket
    "contact@wp-rocket.me",
    # CMC Markets
    "info@mailuk.cmcmarkets.com",
    # EarlyBrd
    "mailgun@smtp.earlybrd.io",
    # Sendgrid / Twilio
    "support@twiliosendgrid.zendesk.com",
    # Ledgerscope
    "support@send.ledgerscope.com",
    # Infinity
    "orders@infinity.coop",
    # Crucial
    "crucialeusupport@micron.com",
    # Appear.in
    "feedback@appear.in",
    # APC Overnight (delivery tracking, not APC Pure client)
    "noreply@apc-overnight.com",
    # Podcast Host
    "noreply@mg.bookme.name",
    # Google Photos
    "noreply-photos@google.com",
    # Mailer daemon bounces
    "mailer-daemon@mta-10.privateemail.com (mail delivery system)",
}


def classify_message(msg):
    """Classify a single message. Returns category string."""
    email = msg["from_email"].lower().strip()
    domain = email.split("@")[-1] if "@" in email else ""
    subject = (msg.get("subject") or "").lower()
    from_name = (msg.get("from_name") or "").lower()

    # ── 1. Definite KEEP ──────────────────────────────────────────────────

    # Personal / Family
    if email in PERSONAL_SENDERS:
        return "reference"

    # Financial / Accounting / Tax
    if email in FINANCIAL_SENDERS:
        return "reference"

    # Clients / Key work contacts
    if email in CLIENT_SENDERS:
        return "reference"

    # Upwork room messages (actual client conversations)
    if email.startswith("room_") and email.endswith("@upwork.com"):
        return "reference"

    # Hosting keep
    if email in HOSTING_KEEP_SENDERS:
        return "reference"

    # ── 2. Definite ARCHIVE ───────────────────────────────────────────────

    if email in ARCHIVE_SENDERS:
        return "archive"

    # ── 3. Pattern-based rules ────────────────────────────────────────────

    # Financial keywords in subject → keep
    financial_keywords = [
        "invoice", "statement", "payment", "receipt", "tax",
        "hmrc", "vat", "pension", "payroll", "salary", "wage",
        "billing", "direct debit", "refund", "bank",
        "companies house", "annual return", "confirmation statement",
    ]
    for kw in financial_keywords:
        if kw in subject:
            return "reference"

    # Government domains → keep
    if domain.endswith(".gov.uk"):
        return "reference"

    # Client-related subject patterns → keep
    client_keywords = [
        "project", "proposal", "contract", "scope", "brief",
        "deadline", "deliverable", "milestone",
    ]
    for kw in client_keywords:
        if kw in subject:
            return "reference"

    # Marketing / newsletter signals → archive
    marketing_signals = [
        "unsubscribe", "newsletter", "weekly digest", "don't miss",
        "% off", "sale ends", "free trial", "exclusive",
        "last chance", "deals", "shop now", "new feature",
        "view in browser", "introducing", "webinar",
        "tips for", "best practice",
    ]
    for kw in marketing_signals:
        if kw in subject:
            return "archive"

    # Notification patterns → archive
    notification_patterns = [
        r"your order .* has",
        r"order confirmation",
        r"delivery update",
        r"tracking number",
        r"has been shipped",
        r"new sign.?in",
        r"verify your",
        r"confirm your email",
        r"welcome to",
        r"thanks for signing up",
        r"password reset",
        r"security alert",
    ]
    for pattern in notification_patterns:
        if re.search(pattern, subject):
            return "archive"

    # noreply senders not already classified → archive
    if any(x in email for x in ["noreply", "no-reply", "no_reply", "donotreply", "do_not_reply", "do-not-reply"]):
        return "archive"

    # Marketing sender patterns → archive
    if any(x in email for x in ["marketing@", "newsletter@", "news@", "promo@", "offers@", "campaign@"]):
        return "archive"

    # ── 4. Default: bias toward archive ───────────────────────────────────
    return "archive"


def main():
    with open(INPUT) as f:
        messages = json.load(f)

    classified = []
    stats = Counter()

    for msg in messages:
        category = classify_message(msg)
        stats[category] += 1
        classified.append({
            "msg_id": msg["msg_id"],
            "from_email": msg["from_email"],
            "from_name": msg["from_name"],
            "subject": msg["subject"],
            "date": msg["date"],
            "category": category,
        })

    with open(OUTPUT, "w") as f:
        json.dump(classified, f, indent=2)

    print(f"Total: {len(classified)}")
    for cat, count in stats.most_common():
        print(f"  {cat}: {count}")

    # Top 20 reference senders
    ref_senders = Counter()
    for m in classified:
        if m["category"] == "reference":
            ref_senders[m["from_email"]] += 1
    print(f"\nTop 20 REFERENCE senders:")
    for email, count in ref_senders.most_common(20):
        name = next(c["from_name"] for c in classified if c["from_email"] == email)
        print(f"  {count:>5}  {email}  ({name})")

    # Top 20 archive senders
    arc_senders = Counter()
    for m in classified:
        if m["category"] == "archive":
            arc_senders[m["from_email"]] += 1
    print(f"\nTop 20 ARCHIVE senders:")
    for email, count in arc_senders.most_common(20):
        name = next(c["from_name"] for c in classified if c["from_email"] == email)
        print(f"  {count:>5}  {email}  ({name})")


if __name__ == "__main__":
    main()
