# Story 1.2 — "Reading the Book"
## PDF Extraction + Licensing + Subprocess Safety

> **Interview value**: Licensing decisions, security through process isolation, multi-library cascade design, and a real bug you found and fixed. All fantastic interview material.

---

## 😤 Why is PDF Extraction Hard?

Before writing a single line of code, it's worth understanding why PDFs are tricky.

A PDF is **not** like a Word document or HTML page. It's closer to a list of printer instructions: "draw this character at coordinate (x=120, y=340), using this font, at this size." There's no built-in concept of "paragraph" or "section."

Three types of PDFs make this even harder:

| Type | What it is | Challenge |
|------|-----------|-----------|
| **Digital-native** | Text encoded as real characters | Easy to extract — library reads the characters directly |
| **Scanned** | Photo of a printed page | The "text" is pixels, not characters — need OCR |
| **Tables** | Structured grid data | Extracting as text flow destroys the structure |

Real textbooks often contain all three in the same document. That's what we had to handle.

---

## 🚨 The Licensing Decision (Critical — Must Know This)

The most popular Python PDF library is **PyMuPDF**, also imported as `fitz`. Fast, feature-rich, well-documented. The obvious choice.

Except... its license is **AGPL-3.0** (Affero General Public License).

### What AGPL-3.0 Actually Means for a SaaS Startup

AGPL has a "viral" clause: if you build a commercial web service using AGPL-licensed code, **you must open-source your entire product** under AGPL. Not just the PDF code — your whole backend. All your business logic, all your AI prompts, all your algorithms.

For a startup that plans to charge students and has investors, this is a business-ending constraint. Publishing your entire codebase as open-source immediately removes your technical competitive advantage.

### The Solution: pypdfium2

pypdfium2 does the same job as PyMuPDF. License: **Apache 2.0**. Apache 2.0 is commercial-friendly — you can use it in closed-source SaaS freely.

This became a hard rule in CLAUDE.md:
```
# Never import fitz/pymupdf/pymupdf4llm/borb — all AGPL-3.0
# PDF extraction uses pypdfium2 + pdftext instead
```

And in every file that touches PDFs, you'll find the comment:
```python
# PyMuPDF (fitz) BANNED — AGPL-3.0 incompatible with closed-source SaaS
```

> **Interview tip**: "We rejected PyMuPDF despite its popularity because AGPL-3.0 would require open-sourcing our entire SaaS codebase. We used pypdfium2 (Apache 2.0) instead — same functionality, commercial-safe license."

---

## 📚 The 5-Library Stack

We used five libraries, each with a specific job:

```
PDF File
   │
   ├──► pypdfium2  ──► Raw text (character-accurate, fast)
   │
   ├──► pdftext   ──► Font metadata (size, bold, name per span)
   │                  └─► Used by structure_node (Story 1.3) to detect headings
   │
   ├──► pdfplumber ──► "Does this page have a table?"
   │                  └─► If YES → hand off to docling
   │
   ├──► docling   ──► Whole-document → clean markdown (table-aware)
   │                  └─► Only runs when pdfplumber found tables
   │
   └──► pytesseract──► OCR: page rendered at 300 DPI → text
                       └─► Only runs when avg chars/page < threshold AND docling skipped
```

### Why this cascade?

Each library handles the case the previous one can't:

1. **pypdfium2** is the workhorse — fast and accurate for digital-native PDFs (97% of cases)
2. **pdftext** piggybacks on pypdfium2's rendering to extract font metrics — we need this for heading detection
3. **pdfplumber** is only used to answer one question: "is there a table on this page?" It's retained solely for this trigger, not for text extraction
4. **docling** converts the *entire document* to table-aware markdown when any page has tables. Why the whole document? Because docling's structured markdown is uniformly better quality than raw pypdfium2 text for table-heavy documents.
5. **pytesseract** is the fallback for scanned PDFs. If the average characters per page is very low (below an `ocr_threshold` env var), the pages are likely images — run OCR.

---

## 🔒 Security: Why Run in an Isolated Subprocess?

Imagine a malicious PDF (or just a badly-formed one from a 1980s scanner). Parsing it might cause the library to:
- Crash with a segfault
- Consume 100% CPU in an infinite loop
- Exhaust all available memory

If this happens **inside the ARQ worker process**, all pending lesson jobs for all users stop working. One bad PDF takes down the queue for everyone.

**The fix**: Run the PDF parser in a completely separate subprocess.

```python
# In extract_node (graph.py)
proc = await asyncio.create_subprocess_exec(
    sys.executable, "-m", "app.modules.content.pipeline.nodes.extract_subprocess",
    pdf_path, img_dir, str(settings.ocr_threshold),
    stdout=asyncio.subprocess.PIPE,
    stderr=asyncio.subprocess.PIPE,
)
stdout, stderr = await proc.communicate()
result = json.loads(stdout)  # Only clean data crosses the boundary
```

If the subprocess crashes: `proc.returncode != 0`, we get an error, that one job fails. The ARQ worker process is completely unaffected. Everyone else's jobs continue normally.

> **Analogy**: A bank teller never handles cash directly — a specialist in a locked room counts the money and passes the slip through a slot. The teller can't be hurt by counterfeit bills.

This pattern is called **process isolation** and it's a standard defense-in-depth technique.

---

## 📸 The 300 DPI Rule

When we need to OCR a page or extract embedded images, we render the PDF page as a bitmap first. The resolution matters enormously for Tesseract's accuracy:

| Resolution | Tesseract Accuracy | Why |
|-----------|-------------------|-----|
| 72 DPI (PDF native) | ~60% | Images are blurry and pixelated |
| 150 DPI | ~80% | Better, but still misses details |
| **300 DPI** | **~95%** | Print-quality — standard for OCR |
| 600 DPI | ~96% | Marginal gain, 4× the memory |

The code:
```python
bitmap = pdfium_page.render(scale=300/72)  # scale=4.17 = 300 DPI
```

`scale=300/72` means "zoom 4.17× beyond the PDF's native resolution before rendering." This is a hard rule in CLAUDE.md: **"PDF image extraction must render at 300 DPI minimum."**

---

## 🐛 The Bug We Found and Fixed

This is a great interview story about defensive programming.

### The Bug

When pytesseract is not installed, `_ocr_page_text()` catches the ImportError and returns `""` (empty string) for every page.

The original code then did:
```python
# BUGGY CODE
raw_text = "\n\n".join(ocr_parts)
# If ocr_parts = ["", "", "", ""] → raw_text = ""
# This OVERWRITES the good pypdfium2 text with an empty string!
```

Joining a list of empty strings gives you an empty string. And then assigning it unconditionally **wipes out the valid text we already extracted with pypdfium2**.

### Why This Was Silent

No exception. No warning. No error. The pipeline would continue happily — creating zero-character chunks, storing zero-useful embeddings, and the student would get an empty lesson with no indication of what went wrong.

### The Fix
```python
# FIXED CODE
ocr_text = "\n\n".join(ocr_parts)
if ocr_text.strip():          # Only overwrite if OCR actually produced text
    raw_text = ocr_text
```

One extra guard. If OCR produces nothing, preserve the original pypdfium2 extraction.

Also fixed a deprecated API call:
```python
# BEFORE (deprecated)
text = textpage.get_text_range()

# AFTER (current API)
text = textpage.get_text_bounded()
```

> **Interview lesson**: "Always add guards before overwriting existing data with processed results. If processing produces nothing, preserving the original is almost always the right default."

---

## ⭐ STAR Interview Answer

**Situation**

We needed to reliably extract text from student-uploaded textbooks. PDFs are notoriously difficult — they mix scanned pages, digital-native text, and complex tables, often in the same document. The obvious tool for this was PyMuPDF — fast, popular, well-documented. But its AGPL-3.0 license would have required open-sourcing our entire SaaS codebase, which was not acceptable for a commercial startup.

**Task**

Build a multi-library PDF extraction stack that handles all three PDF types (digital-native, scanned, table-heavy) — running in an isolated subprocess for crash safety — while strictly avoiding AGPL-licensed dependencies.

**Action**

- Researched PDF library licensing: rejected PyMuPDF (AGPL-3.0), selected pypdfium2 (Apache 2.0) as the primary extractor
- Designed a 5-library cascade: pypdfium2 for text → pdfplumber for table detection → pdftext for font metadata → docling for table markdown → pytesseract OCR fallback
- Implemented subprocess isolation so a malformed PDF cannot crash the ARQ worker process and stop all other users' jobs
- Set OCR render resolution to 300 DPI (`scale=300/72`) to maintain Tesseract accuracy above 95%
- Discovered and fixed a silent data-corruption bug: empty OCR output was unconditionally overwriting valid pypdfium2 text — added a `if ocr_text.strip()` guard
- Fixed a deprecated pypdfium2 API call (`get_text_range()` → `get_text_bounded()`)

**Result**

Production-ready PDF extraction that handles all three real-world PDF types. Subprocess isolation means a malformed PDF can never take down the job queue. 300 DPI ensures OCR meets production accuracy standards. Zero AGPL exposure in the codebase.

---

## 📖 Key Terms Glossary

| Term | Plain English |
|------|--------------|
| **AGPL-3.0** | A software license that requires open-sourcing your entire product if you use it in a commercial service |
| **Apache 2.0** | A permissive license — commercial-friendly, no viral clause |
| **OCR** | Optical Character Recognition — software that reads text from images |
| **DPI** | Dots Per Inch — higher = sharper image = better OCR |
| **subprocess** | A completely separate Python process, isolated from the parent |
| **magic bytes** | The first few bytes of a file that identify its type (`%PDF` for PDFs, `MZ` for Windows executables) |
| **pypdfium2** | Python bindings for PDFium — Google's PDF rendering engine (same one used in Chrome) |
| **pdftext** | Extracts structured font metadata (size, bold flag) per text span |
| **docling** | IBM's document intelligence library — converts PDFs to structured markdown |
| **pytesseract** | Python wrapper for Google's Tesseract OCR engine |
