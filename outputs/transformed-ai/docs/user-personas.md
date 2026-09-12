# TransformED AI — Target Learner Personas

Derived from the product's own market signals: INR pricing tiers, Sarvam (Indian-language) TTS, DPDP Act framing, and a textbook-chapter-driven learning flow aimed at school and exam-prep content. These personas are used in `launch-readiness-plan.md` to justify priority calls — notably, personas 1 and 3 are the direct reason the missing parental-consent gap (see `product-audit.md` §3) is a P0, not a P1.

---

## 1. Ananya, 16 — Board-exam student, Tier-2 city

- **Context:** Class 11, studies from NCERT/state-board textbooks, shares one family smartphone/laptop with a sibling. Home wifi is inconsistent; often studies late evening on mobile data.
- **Goal:** Turn a dense 40-page textbook chapter into something she can actually get through before a test, without a tutor.
- **Motivation:** Board exam pressure is high-stakes and family-monitored; she wants to feel like she's actually retaining material, not just watching a video passively.
- **Pain points:** Generic YouTube explainer videos are unpaced to her level; she can't ask a video "wait, why?" Textbook language is denser than how her teacher explains it. She gets embarrassed asking "basic" questions in a group tutoring class.
- **Behavior:** Studies in short bursts between other obligations; abandons anything that takes more than a few taps to start; trusts a product more if a friend recommended it.
- **Product implication:** The teach-back and jargon-tooltip features map directly to her real pain point (denser textbook language). But she is a minor, and the webcam-based attention monitoring currently has **no parental consent flow** — a direct product gap against this exact persona.

## 2. Rohan, 24 — Competitive-exam aspirant, self-directed

- **Context:** Preparing for a competitive entrance/civil-services-style exam, studying independently (drop-year or working alongside prep), often in a shared PG (paying-guest) room with limited privacy.
- **Goal:** Maximize retention-per-hour across a huge syllabus; needs both first-pass learning and efficient revision.
- **Motivation:** Time is the scarce resource, not motivation — he's already disciplined, but needs the material compressed and tested, not just read.
- **Pain points:** Doesn't want to re-watch a full lesson to revise one weak topic; wants to know objectively where he's weak, not just "did you finish the chapter."
- **Behavior:** Comfortable with technology, will actually use adaptive/analytics features if they're real and trustworthy; skeptical of AI hype claims and will notice if "adaptive personalization" doesn't actually adapt anything.
- **Product implication:** He is exactly the user who will test — and be disappointed by — the current gap between "Learner DNA" as marketed and as built (see `product-audit.md` §4). He is also the primary audience for the not-yet-built "revision mode" video feature.

## 3. Meera, 42 — Parent/guardian of a younger learner

- **Context:** Pays for the product on behalf of a child around age 12–14; herself moderately tech-comfortable (uses banking apps, WhatsApp, UPI) but not a power user.
- **Goal:** Wants her child to get real help with schoolwork without her having to sit and supervise every session.
- **Motivation:** Trust and safety come before features — a webcam pointed at her child during study time is the kind of detail she will specifically ask about before paying.
- **Pain points:** Doesn't want to read a legal consent document; wants a plain-language yes/no about what the camera does, who sees the data, and how to turn it off. Will not knowingly agree to data leaving India given recent news awareness of data-privacy issues.
- **Behavior:** Makes the purchasing decision, but is not the one using the product session-to-session — meaning consent and account controls need to work for *her*, not just for the child logged in.
- **Product implication:** She is the persona that exposes the sharpest current gap: there is no parental-consent or guardian-account mechanism at all today. The existing consent modal is well-written for an adult reading it — but nothing routes that consent through a parent for a minor's account. Her other core need — the ability to delete her child's data on request — is technically supported by the schema but **not actually reachable**, because the "Delete Account" button in settings has no working handler.

---

### How to use these personas

- Persona 1 (Ananya) and Persona 3 (Meera) together are the justification for treating the missing minors/parental-consent flow as a **launch blocker**, not a backlog item — the product's actual target user is frequently a minor, and the person paying is frequently not the person using it.
- Persona 2 (Rohan) is the justification for being precise in launch marketing about what "Learner DNA" currently does versus what it's designed to eventually do.
