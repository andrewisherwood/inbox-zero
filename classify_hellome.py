#!/usr/bin/env python3
"""Classify hellome pass2_remaining.json messages into categories."""

import json
import re
from datetime import datetime

INPUT = "triage_output/hellome/pass2_remaining.json"
OUTPUT = "triage_output/hellome/pass2_classification.json"

# ── KEEP: Personal / Family ──────────────────────────────────────────────────
PERSONAL_SENDERS = {
    "lilymarcel27@gmail.com",           # Wife/partner — Lily Marcel
    "lily.marcel@cliffordchance.com",   # Lily work email
    "isherwoodsimon@gmail.com",         # Simon Isherwood — family
    "isherwood_j@hotmail.com",          # James Isherwood — family
    "apisherwood@gmail.com",            # Anne Isherwood — family
    "benjamin.j.isherwood@googlemail.com",  # Ben Isherwood — family
    "mdfazlarabbi1992@gmail.com",       # fazla rabbi — personal contact
    "josiesanders@hotmail.com",         # Josie Sanders — personal
    "ecrook16@yahoo.co.uk",            # Elaine Crook — personal
    "morethanplaying@gmail.com",        # Alanna Thrower — personal
    "classof2029whsjunior@gmail.com",   # School parent group
    "alice@alicebaer.com",              # Alice Baer — therapist/counsellor
    "alice.baer@tunbridgewellscounsellinghub.com",  # Alice Baer counselling
    "anna@kingsleycounselling.com",     # Anna Kingsley — counsellor
    "kentoninteriors@gmail.com",        # Chris Kenward — personal/tradesperson
    "elsie.blackshaw@lifescapeproject.org",  # Elsie — personal contact
    "adam.eagle@lifescapeproject.org",   # Adam Eagle — personal contact
    "stephanie.smith@lifescapeproject.org",  # Stephanie Smith — personal contact
    "gordon.rennie@sap.com",            # Gordon Rennie — personal contact
    "john@artyparty.co.uk",             # Arty Party — kids activities
    "michael@thehouselondon.com",       # Michael Murdoch — personal contact
    "brooke.warner@blckbx.co.uk",       # Brooke Warner — personal contact
    "cleona@celticfp.co.uk",            # Cleona — financial planner (personal)
    "cleona@consciousmoney.co.uk",      # Cleona Lira — financial planner
    "rob@londoncampers.co.uk",          # Rob London Campers — personal/rental
    "jess@morethanlofts.com",           # Jess O'Connor — loft builder
    "e.parr@rygroup.co.uk",             # Ellis Parr — personal contact
    "richard@hillclements.com",         # Richard Howell — personal contact
    "p.hayles@mhsurveyors.com",         # Phil Hayles — surveyor (property)
    "renatejones@wimbledonnannies.com", # Nanny agency
    "clairegordon@wimbledonnannies.com",# Nanny agency
    "jean@nannymatters.co.uk",          # Nanny agency
    "admin@advancedcarhire.com",        # Car hire — personal
    "toby@blackradishsw19.com",         # Local restaurant owner — personal
    "lucy.e.isherwood@gmail.com",       # Lucy Isherwood — family
    "tracey.isherwood@googlemail.com",  # Tracey Isherwood — family
    "lucy.e.brown@googlemail.com",      # Lucy Brown — family/personal
    "chefandrewisherwood@gmail.com",    # Andy's own email
    "outlook_894aa2b694dc4cc4@outlook.com",  # Alice Baer alt email
    "hannahcatherinejames@gmail.com",   # Hannah James — personal/work
    "finestone796@gmail.com",           # Michael Finestone — builder
    "finestonedan@gmail.com",           # Dan Finestone — builder
    "pankajkumar66@hotmail.com",        # Pankaj Kumar — tradesperson
    "minzhao0208@gmail.com",            # Min Zhao — school parent
    "uniformwhssecondhand@gmail.com",   # School uniform
    "ewa.gorska7465@gmail.com",         # Ewa Gorska — play therapy
    "nickcarter884@hotmail.com",        # Nick Carter — personal
    "lunderskovs@gmail.com",            # Dorte Lunderskov — personal
    "pippahainsworth@yahoo.com",        # Pippa Hainsworth — personal
    "roger.hallam.uk@gmail.com",        # Roger Hallam — personal
}

# ── KEEP: School / Flora ─────────────────────────────────────────────────────
SCHOOL_DOMAINS = {
    "wim.gdst.net",             # Wimbledon High School
    "wes.gdst.net",             # Related GDST school
}
SCHOOL_SENDERS = {
    "platform@parentpay.com",
    "customerservices@schoolblazer.com",
    "parents@parents.schoolblazer.com",
    "noreply@schoolcloud.co.uk",
    "tennis@wim.gdst.net",
    "info@tjsgymclub.co.uk",     # Kids gymnastics
    "climb@whitespiderclimbing.com",  # Kids climbing
}

# ── KEEP: Medical / ADHD ─────────────────────────────────────────────────────
MEDICAL_SENDERS = {
    "appointments@curaleafclinic.com",
    "hello@alternaleaf.co.uk",
    "info@alternaleaf.co.uk",
    "no-reply@adhd-360.com",
    "enquiries@adhd-360.com",
    "reception@sthelierdental.co.uk",
    "sthelier@confidentalclinic.com",
    "noreply@visionexpress.com",
    "alerts@e-bluecresthealth.com",
    "noreply@mail.riviam.io",
    "raynespark@davidlloyd.co.uk",  # Health/gym membership
}

# ── KEEP: Financial / Banking / Insurance ─────────────────────────────────────
FINANCIAL_SENDERS = {
    "no-reply@communications.nationwide.co.uk",
    "noreply@mail.zopa.com",
    "no-reply@service.hl.co.uk",
    "hargreaveslansdown@service.contact.hl.co.uk",
    "documents@secure.fidelity.co.uk",
    "notification@email.fidelity.co.uk",
    "luke.stower@investec.com",
    "privatebanking@email.investec.co.uk",
    "dav.gedhu@investec.com",
    "donotreply@starlingbank.com",
    "service@updates.starlingbank.com",
    "no_reply@communications.paypal.com",
    "do_not_reply@mailersp1.binance.com",
    "do_not_reply@mailersp2.binance.com",
    "support@mail.gate.io",
    "no-reply@ramp.network",
    "ledger@delivery.ledger.com",
    "noreply@optimism.com",
    "admin@banfaucet.com",
    "lv@insurance.lv.co.uk",
    "lv.documents@lv.co.uk",
    "support@stripe.com",
    "quickbooks@notification.intuit.com",
    "messaging-service@post.xero.com",
    "invoice+statements@midjourney.com",
    "accounts@fraziers.co.uk",
    "customer.service@bordeauxindex.com",
    "hello@mail.getchip.uk",
    "receipts+acct_1ovbcadhttioxkgp@stripe.com",
    "shopper@worldpay.com",
    "no-reply@accounts.google.com",
    "adobesign@adobesign.com",
    "dse@eumail.docusign.net",
    "s0mtk4auss2gj69nomwiqa@getinvoicesimple.com",
}

# ── KEEP: Solicitors / Property / Government ──────────────────────────────────
PROPERTY_LEGAL_SENDERS = {
    "shelley.burt@twmsolicitors.com",
    "damon.bleau@twmsolicitors.com",
    "vanessa.burt@twmsolicitors.com",
    "bella.fox@twmsolicitors.com",
    "client.onboarding@twmsolicitors.com",
    "paul.mannell@hawesandco.co.uk",
    "marcus.short@hawesandco.co.uk",
    "ria.lawrence@hawesandco.co.uk",
    "boundsr@hamptons.co.uk",
    "crampr@hamptons.co.uk",
    "noreply@hamptons.co.uk",
    "tony.spinks@goodfellows.co.uk",
    "anitab@winchester-white.co.uk",
    "struttandparker@residential.struttandparker.com",
    "info@universalflooring.uk",
    "quote@clockworkremovals.co.uk",
    "local.taxation@merton.gov.uk",
    "electoral.services@merton.gov.uk",
    "noreply@book.merton.gov.uk",
    "donotreply@thameswater.co.uk",
    "noreplymetering@thameswater.co.uk",
    "fms-do-not-reply@fixmystreet.com",
    "no-reply@petition.parliament.uk",
    "notifications.noreply@communityfibre.co.uk",
    "members@lifetimelegal.co.uk",
    "hello@octopus.energy",           # Energy bills — financial
    "myaccount@milkandmore.co.uk",    # Regular delivery — household
    "support@joinbubble.com",         # Childcare platform
}

# ── KEEP: Childcare / Nursery ─────────────────────────────────────────────────
CHILDCARE_SENDERS = {
    "payroll@nannymatters.co.uk",
    "thamesditton.admin@busybees.com",
    "morden.centredirector@busybees.com",
}

# ── ARCHIVE: Definite noise ──────────────────────────────────────────────────
ARCHIVE_SENDERS = {
    "no_reply@freecycle.org",
    "info@britishgravelchampionships.com",
    "newsletter@mail.ridewithgps.com",
    "marketing@clearscore.com",
    "updates@clearscore.com",
    "alerts@clearscore.com",
    "noreply@intervals.icu",
    "messages@intervals.icu",
    "news@news.movember.com",
    "info@news.progreen.uk",
    "newsletter@emails.comparethemarket.com",
    "renewals@emails.comparethemarket.com",
    "hello@chess.com",
    "team@mail.carbmanager.com",
    "info@ptpcoaching.co.uk",
    "noreply@tezlabapp.com",
    "noreply@tradeinn.com",
    "no-reply@victorianplumbing.co.uk",
    "no-reply@squarespace.com",
    "no-reply@playmemoriesonline.com",
    "noreply@gopro.com",
    "subscriptions@gopro.com",
    "accounts@gopro.com",
    "noreply@dm.insta360.com",
    "support@magicvaporizers.com",
    "noreply@thegrasspeople.com",
    "news@lovetheatre.com",
    "hello@email.jaqueslondon.co.uk",
    "do_not_reply@mountainwarehouse.com",
    "satoru@mailer.wagamama.com",
    "noreply@wagamama.com",
    "email@service.marksandspencer.com",
    "halfords@halfords.com",
    "noreply@halfords.com",
    "halfords.direct@halfords.co.uk",
    "noreply@prod.halfordspace.com",
    "no-reply@mailsender.runnersneed.com",
    "loyaltyclub@chessingtongardencentre.co.uk",
    "info@cooksongold.com",
    "sales@kleankanteen.co.uk",
    "noreply@survey.os.uk",
    "noreply@yotoplay.com",
    "daniel@wildthingspublishing.com",
    "hello@joizi.com",
    "personalpa@ski-boutique.co.uk",
    "noreply@news.bipandgo.com",
    "shop@noblerot.co.uk",
    "sael@email.sevenrooms.com",
    "drink@whitehorsemayfair.co.uk",
    "reservations@hide.co.uk",
    "newsletter@gauthiersoho.co.uk",
    "hello@organicbutchery.co.uk",
    "shop@shrinetothevine.co.uk",
    "customers@misterchampagne.ch",
    "info@misterchampagne.ch",
    "wine@thelondonwinecellar.com",
    "info@bbno.co",
    "email@mail.milkandmore.co.uk",  # Marketing (diff from account emails)
    "noreply@tesla.com",
    "no-reply@service.tesla.com",
    "info@search4parts.co.uk",
    "support@cycleexchange.co.uk",
    "support@roborock-eu.com",
    "contact@mygarminstraps.shop",
    "contact@tiallannec.com",
    "info@chillypowder.com",
    "noreply@myguestdiary.com",
    "info@nautichill.com",
    "hello@lakelandactive.com",
    "suttonsportsvillage@gll.org",
    "noreply@smartwaiver.com",
    "info@eventrac.co.uk",
    "notifications@courtreserve.com",
    "notifications@evcharge.online",
    "customerservice@pret-a-portrait.net",
    "donotreply@seetickets.com",
    "atgtickets@atg.atgtickets.com",
    "no-reply@service.odeon.co.uk",
    "no-reply@kinsen.gr",
    "info@lagoletahoteldemar.com",
    "sales@thepolycarbonatestore.co.uk",
    "noreply@toolstation.com",
    "support@bikegoo.co.uk",
    "mail@bookings.bikerentalmanager.com",
    "membership@nhm.ac.uk",
    "paperlesspost@paperlesspost.com",
    "paperlesspost@accounts.paperlesspost.com",
}

# ── ARCHIVE: Sender domain patterns ──────────────────────────────────────────
ARCHIVE_DOMAINS = {
    "emop.world",               # Cleaning service (all addresses)
    "outdoorsy.co",             # Rental platform notifications
    "easyjet.com",              # Travel marketing/confirmations (old)
    "email.ba.com",             # BA marketing
    "dot-air.com",              # BA automated
    "ouigo.com",                # French trains
    "pasngr.ouigo.com",         # French trains
}


def classify_message(msg):
    """Classify a single message. Returns category string."""
    email = msg["from_email"].lower()
    domain = email.split("@")[-1] if "@" in email else ""
    subject = (msg.get("subject") or "").lower()
    from_name = (msg.get("from_name") or "").lower()

    # ── 1. Definite KEEP categories ───────────────────────────────────────

    # Personal / Family
    if email in PERSONAL_SENDERS:
        return "reference"

    # School
    if domain in SCHOOL_DOMAINS or email in SCHOOL_SENDERS:
        return "reference"

    # Medical / ADHD
    if email in MEDICAL_SENDERS:
        return "reference"

    # Financial / Banking
    if email in FINANCIAL_SENDERS:
        return "reference"

    # Property / Legal / Government
    if email in PROPERTY_LEGAL_SENDERS:
        return "reference"

    # Childcare
    if email in CHILDCARE_SENDERS:
        return "reference"

    # ── 2. Definite ARCHIVE ───────────────────────────────────────────────

    if email in ARCHIVE_SENDERS:
        return "archive"

    if domain in ARCHIVE_DOMAINS:
        return "archive"

    # ── 3. Pattern-based rules ────────────────────────────────────────────

    # Financial keywords in sender or subject → keep
    financial_keywords = [
        "invoice", "statement", "payment", "receipt", "tax", "hmrc",
        "pension", "mortgage", "insurance", "solicitor", "conveyancing",
        "council tax", "billing", "direct debit", "refund",
    ]
    for kw in financial_keywords:
        if kw in subject or kw in from_name:
            return "reference"

    # Medical keywords → keep
    medical_keywords = [
        "appointment", "prescription", "clinic", "doctor", "gp ",
        "nhs", "adhd", "medical", "dental", "optician", "pharmacy",
        "health", "cannabis", "curaleaf", "alternaleaf",
    ]
    for kw in medical_keywords:
        if kw in subject or kw in from_name:
            return "reference"

    # School / children keywords → keep
    school_keywords = [
        "school", "flora", "parent", "pupil", "term", "half term",
        "sports day", "nursery", "childcare", "nanny",
    ]
    for kw in school_keywords:
        if kw in subject:
            return "reference"

    # Property keywords → keep
    property_keywords = [
        "tenancy", "tenant", "landlord", "rent ", "lease",
        "property", "house", "flat", "mortgage", "completion",
        "exchange", "survey", "conveyancing", "solicitor",
    ]
    for kw in property_keywords:
        if kw in subject:
            return "reference"

    # Government / official → keep
    gov_keywords = [
        "council", "electoral", "vote", "petition", "gov.uk",
        "merton", "hmrc", "passport",
    ]
    for kw in gov_keywords:
        if kw in subject or kw in domain:
            return "reference"

    # Unsubscribe / newsletter / marketing signals → archive
    marketing_signals = [
        "unsubscribe", "newsletter", "weekly digest", "don't miss",
        "limited time", "% off", "sale ends", "free delivery",
        "exclusive offer", "last chance", "deals", "shop now",
        "view in browser", "new arrivals", "introducing",
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
        r"out for delivery",
        r"new sign.?in",
        r"verify your",
        r"confirm your email",
        r"welcome to",
        r"thanks for signing up",
        r"password reset",
        r"your .* subscription",
    ]
    for pattern in notification_patterns:
        if re.search(pattern, subject):
            return "archive"

    # noreply / no-reply / donotreply senders that aren't already classified → archive
    if any(x in email for x in ["noreply", "no-reply", "no_reply", "donotreply", "do_not_reply", "do-not-reply"]):
        return "archive"

    # Marketing domain patterns → archive
    marketing_domain_patterns = [
        "marketing@", "newsletter@", "news@", "promo@",
        "offers@", "deals@", "campaign@", "email.sevenrooms",
        "mailer.", "mail.", "emails.",
    ]
    for pattern in marketing_domain_patterns:
        if pattern in email:
            return "archive"

    # ── 4. Domain-based heuristics ────────────────────────────────────────

    # .gov.uk → keep
    if domain.endswith(".gov.uk"):
        return "reference"

    # Known financial domains
    financial_domains = [
        "investec", "nationwide", "zopa", "starlingbank", "fidelity",
        "paypal", "stripe", "binance", "hl.co.uk", "clearscore",
    ]
    for fd in financial_domains:
        if fd in domain:
            return "reference"

    # ── 5. Default: bias toward archive ───────────────────────────────────
    # Per project rules: "Bias toward archiving for everything else"
    return "archive"


def main():
    with open(INPUT) as f:
        messages = json.load(f)

    classified = []
    from collections import Counter
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

    # Show top 20 reference senders for sanity check
    ref_senders = Counter()
    for m in classified:
        if m["category"] == "reference":
            ref_senders[m["from_email"]] += 1
    print(f"\nTop 20 REFERENCE senders:")
    for email, count in ref_senders.most_common(20):
        name = next(c["from_name"] for c in classified if c["from_email"] == email)
        print(f"  {count:>5}  {email}  ({name})")

    # Show top 20 archive senders
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
