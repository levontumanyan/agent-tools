---
name: airbnb-host-questions
description: >-
  Draft a concise, human-readable message of pre-booking questions to send an Airbnb host
  for a remote-work/nomad stay (Wi-Fi, cooking/soup kitchen gear, laundry, noise/construction,
  visitor/guest procedure, late check-in, hot water, AC, workspace).
  Automatically inspects a specific listing first and omits anything already confirmed.
---

# Airbnb Host Pre-Booking Questions

Draft a short, friendly, ready-to-send message to confirm deal-breakers before booking a 1-month nomad stay.

# Workflow

1. **If a specific listing URL, room ID, or listing text is provided**:
   - Inspect it first (`airbnb --room <id> --reviews` when the details are not already in context).
   - Check amenities, description, house rules, and recent guest reviews against the checklist below.
   - **Drop any item already clearly confirmed** (e.g., skip laundry if an in-unit washer is confirmed; skip Wi-Fi speed if an official speed-test badge ≥100 Mbps is present; skip check-in if 24/7 smart-lock self check-in is stated; skip AC in cool/mild climates).
   - **Targeted follow-ups**: If the listing or reviews hint at a specific caveat (e.g., *"registered guests only"*, *"street noise"*, *"basic kitchen"*, *"ambient water"*), ask directly about that detail instead of a generic question.
2. **If no specific listing is provided**:
   - Include the core checklist items, grouped tightly so the message still reads naturally.
3. **Language**:
   - Default to English. If the listing is in Spanish or Portuguese (or the user asks), write in that language or provide the local-language version ready to paste.

# Confirmation Checklist

Include only unconfirmed or ambiguous items:

- **Internet (Nomading)**: Confirm actual download/upload speed (ask for a quick speed test if no verified badge), stability for daily video calls, and whether the router is inside the unit.
- **Kitchen (Full Meals & Soup)**: Confirm all stove burners work and whether there's a deep pot for making soup/stews, a pan, a sharp knife, a cutting board, and basic cooking utensils (ladle/spoon).
- **Laundry**: Confirm whether there's an in-unit washing machine (or how shared laundry works) and how clothes are dried (dryer, drying rack, or balcony).
- **Noise & Construction**: Ask if there is any active/upcoming construction in the building or nearby, and how quiet the apartment is at night/weekends (street traffic, bars, dogs).
- **Guests / Visitors**: Ask if it's okay to occasionally have a friend over during the day or for a night, and what the building's registration/ID procedure is.
- **Check-in / Late Arrival**: Confirm the check-in window and how late-night arrivals (or early bag drop) work (smart lock, 24/7 reception, or host handoff).
- **Hot Water & Gas**: In tropical/LatAm listings where hot water isn't guaranteed, confirm reliable hot shower water (and if gas-cylinder based, that a backup/quick swap is covered).
- **AC & Climate Control**: In warm/humid destinations, confirm AC works well in the bedroom/living area so windows can stay closed for quiet sleep.
- **Workspace**: If photos don't clearly show one, confirm there is a proper desk/table and comfortable chair for full-time laptop work.
- **Power / Electricity Reliability**: In cities or areas known for grid instability, ask how reliable the electricity is (any frequent outages) and whether the building has a backup generator.

# Output Style

- **Succinct & human-readable**: Friendly, polite, casual-professional tone — like a considerate long-term guest, not a legal audit.
- **Tight length**: Group related items into **3–6 short numbered points** (~80–150 words total).
- **Ready to paste**: Output the message directly in a clean block so the user can copy-paste it into Airbnb chat. If you omitted items because the listing already confirmed them, add a 1-line note *below* the message listing what was skipped (e.g., *Skipped: in-unit washer, 145 Mbps verified Wi-Fi, 24/7 reception*).
