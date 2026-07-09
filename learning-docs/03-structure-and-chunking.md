# Stories 1.3 + 1.4 — "Making Sense of the Book"
## Structure Detection + Semantic Chunking

> **Interview value**: Two classic NLP/search engineering patterns — document parsing with hybrid heuristics, and chunking strategy for RAG systems. Both come up in ML engineering and backend roles.

---

## 📖 The Problem After Extraction

After Story 1.2, we have raw text — one giant string. This is like getting a textbook where someone cut out all the pages, removed the headers and footers, and gave you just the text in one continuous block. You know the content is there, but you have no idea where Chapter 1 ends and Chapter 2 begins.

Story 1.3 solves the **structure problem**: find the chapters, sections, and sub-sections.  
Story 1.4 solves the **size problem**: break those sections into pieces that fit the AI model.

---

# Story 1.3 — Structure Detection

## 🧠 How Does a Computer Detect Headings?

When you look at a textbook, headings are visually obvious — bigger text, often bold, shorter than body text. We can teach a computer to detect this in two ways:

### Strategy 1: Font-Size Clustering

The `extract_node` (Story 1.2) also collected **font metadata** via pdftext — every text span's font name, size, and whether it's bold. Structure detection uses this:

```python
# Collect all font sizes in the document
sizes = [block["font"]["size"] for block in font_blocks]
median_size = statistics.median(sizes)   # The "normal" body text size

# Any span that is 25%+ bigger AND bold = heading candidate
threshold = median_size * 1.25
for block in font_blocks:
    if block["font"]["size"] >= threshold and block["font"]["bold"]:
        # Determine level by relative size:
        if size >= threshold * 1.15:   level = "chapter"
        elif size >= threshold * 1.05: level = "section"
        else:                          level = "topic"
```

> **Why median instead of average?** A few giant title pages or decorative headings can skew the average dramatically. The median is robust to outliers — it's the true "middle" value.

### Strategy 2: Regex Pattern Matching

Some PDFs (especially digitally-generated ones like lecture slides exported as PDF) don't use larger fonts for headings. They use numbered outlines instead:

```python
_CHAPTER_RE = re.compile(r"^(?:Chapter\s+\d+[\.:]\s*.+|\d+\.\s+[A-Z].{3,})", re.MULTILINE)
_SECTION_RE = re.compile(r"^(\d+\.\d+)\.?\s+[A-Za-z].{2,}", re.MULTILINE)
_TOPIC_RE   = re.compile(r"^(\d+\.\d+\.\d+)\.?\s+[A-Za-z].{2,}", re.MULTILINE)
```

These match patterns like:
- `Chapter 3: Photosynthesis` → chapter
- `3.2 Light Reactions` → section
- `3.2.1 Photosystem I` → topic

Both strategies run and their results are **merged and deduplicated** by heading text (font detection wins over regex when both detect the same heading — font metadata gives more reliable level assignment).

### The LLM Cleanup Pass

Rule-based detection isn't perfect. Common false positives:
- Table headers that happen to be bold
- Figure captions in large text
- Footnote numbers in decorative fonts

A final pass with GPT-4o-mini reviews the candidates:
- Removes false positives
- Adds any headings the rules missed
- Normalizes the hierarchy (fixes a "topic" that's actually a "chapter")

This **hybrid approach** (rules → AI cleanup) is ~80% cheaper than pure-LLM detection because the rules handle 90% of cases and the LLM only cleans up edge cases.

---

## 🌳 Why Structure Before Chunking?

Without structure detection, chunking would cut text at arbitrary token boundaries, potentially splitting in the middle of a paragraph about "Photosynthesis" and continuing into the next paragraph about "Cellular Respiration."

With structure detection, we have a tree:
```
Chapter 3: Photosynthesis
    Section 3.1: What is Photosynthesis?
        [body text here]
    Section 3.2: Light Reactions
        [body text here]
        Topic 3.2.1: Photosystem I
            [body text here]
```

Chunks are always created **within** section boundaries. A chunk about Photosystem I never accidentally contains text from Section 3.3.

---

## ⭐ STAR: Story 1.3 (Structure Detection)

**Situation**

After PDF extraction we had one giant unstructured text blob. Lesson generation requires structured sections — you can't ask a language model to "create a lesson plan for Chapter 3" when it has no idea what's in Chapter 3 vs Chapter 4. A single-document context approach would also be 5× more expensive in tokens.

**Task**

Build a structure detection system that identifies chapters, sections, and topics from raw PDF text and font metadata — without requiring PDFs to follow any specific format, because real textbooks from different publishers look completely different.

**Action**

- Implemented font-size clustering: used pdftext span metadata, calculated median font size, flagged spans 25%+ larger and bold as heading candidates, assigned chapter/section/topic level by relative size tiers
- Implemented regex matching for numbered outline patterns (Chapter X:, 1.2 ..., 1.2.3 ...)
- Merged both strategy outputs, deduplicated by heading text
- Added GPT-4o-mini validation pass to remove false positives (bold table headers, figure captions) and normalize the hierarchy

**Result**

Hybrid detection works on both scanned PDFs (font strategy) and digitally-native PDFs (regex strategy). ~80% cheaper than pure-LLM detection because rules handle most cases. Output feeds directly into the chunking node as properly bounded sections.

---

---

# Story 1.4 — Semantic Chunking

## ✂️ Why Chunk?

Language models have context windows — a maximum amount of text they can process at once. The OpenAI text-embedding-3-small model has a practical limit of ~8,000 tokens per input. A full textbook section can be 10,000+ tokens. We need to split it.

More importantly: **search works better with smaller, focused pieces.** When a student asks "explain photosynthesis," we want to retrieve the specific 3-paragraph section about photosynthesis — not a 20-page chapter that happens to contain that word somewhere.

## 📏 The Goldilocks Problem

**Too small** (e.g., 100 tokens ≈ 1-2 sentences):
- A chunk might be: "However, this process requires sunlight."
- Without context, what process? Useless in retrieval.

**Too large** (e.g., 2000 tokens ≈ 15 paragraphs):
- Contains too many topics — retrieval becomes noisy
- Embedding tries to represent 15 different ideas in one vector

**512 tokens** ≈ 3-5 paragraphs:
- Enough context to understand what the text is about
- Focused enough to be about one main idea
- Fits comfortably within the embedding model's window

## 🧮 The Chunking Algorithm

The algorithm is **greedy sentence packing with overlap**:

```
Target: 512 tokens. Overlap: 64 tokens.

Section text:
"Photosynthesis is the process... [sentence 1, 45 tokens]
 Chlorophyll absorbs... [sentence 2, 38 tokens]
 The light reactions... [sentence 3, 52 tokens]
 ...
 [sentence 12, 48 tokens] ← adding this would exceed 512 → flush!
 
 Chunk 1: sentences 1-11 (with overlap_prefix = "")
 
 overlap_prefix = last 64 tokens of Chunk 1 (≈ sentence 11)
 
 Chunk 2 starts: overlap_prefix + sentence 12 + sentence 13 + ...
"
```

Step by step:
1. Split the section body into sentences (using regex on punctuation boundaries)
2. Maintain a "buffer" of sentences being accumulated
3. For each new sentence: check if adding it would exceed 512 tokens
4. If yes: flush the buffer as a chunk, save the last 64 tokens as the overlap prefix
5. If no: add the sentence to the buffer, continue
6. At the end: flush remaining buffer as the final chunk

### The Overlap — Why Repeat 64 Tokens?

```
Without overlap:
  Chunk 1: "...The key enzyme involved is RuBisCO, which catalyzes"
  Chunk 2: "the first step of the Calvin cycle by combining CO₂..."
  
  Searching for "how does RuBisCO work" → finds Chunk 1 (mentions RuBisCO)
  But the answer is split across BOTH chunks!

With 64-token overlap:
  Chunk 1: "...The key enzyme involved is RuBisCO, which catalyzes"
  Chunk 2: "RuBisCO, which catalyzes [repeated] the first step of the Calvin cycle by combining CO₂..."
  
  Searching for "how does RuBisCO work" → Chunk 2 now contains both the term AND its explanation!
```

Overlap ensures that concepts spanning a chunk boundary are retrievable from either side.

## 🔤 Why cl100k_base Tokenizer?

A "token" is not a word. It's a subword unit. The tokenizer converts text → tokens, and different models use different tokenizers.

text-embedding-3-small uses **cl100k_base** (same as GPT-4o).

If we counted words or characters instead of tokens:
- "antidisestablishmentarianism" = 1 word, but ~5 tokens
- "AI" = 1 word, but 1 token
- Our "512 token" chunk might actually be 700 tokens and get **silently truncated** by the model when it processes it

Using the exact tokenizer guarantees our chunks always fit without silent truncation.

```python
import tiktoken
encoding = tiktoken.get_encoding("cl100k_base")

# Count tokens accurately
token_count = len(encoding.encode(text))

# Overlap is done at the token level:
all_tokens = encoding.encode(full_chunk_text)
overlap_tokens = all_tokens[-64:]            # Last 64 tokens
overlap_prefix = encoding.decode(overlap_tokens)  # Back to text
```

## ⭐ STAR: Story 1.4 (Semantic Chunking)

**Situation**

Sections from Story 1.3 could be thousands of tokens long — well beyond what the embedding model can meaningfully encode in a single vector. We needed to split them into chunks that fit the model's window, while preserving semantic coherence (no mid-sentence breaks) and context at boundaries.

**Task**

Implement a chunking algorithm targeting 512 tokens per chunk with 64-token overlap, never breaking mid-sentence, using the exact tokenizer of the embedding model.

**Action**

- Used tiktoken with cl100k_base — the exact same tokenizer as text-embedding-3-small and GPT-4o — so token counts are precise, not approximated
- Implemented greedy paragraph-then-sentence packing: fill a buffer sentence by sentence until adding the next would exceed 512 tokens
- Added 64-token overlap via token-level tail decoding: `encoding.decode(all_tokens[-64:])` — exact token-level overlap, not word approximation
- Stored each chunk in Supabase with: `chunk_id`, `content`, `token_count`, `chapter_id`, `chunk_index` (ordered for checkpoint-based processing in Story 1.5)

**Result**

All chunks are token-accurate (never silently truncated by the model), semantically complete (no mid-sentence breaks), and cross-boundary context is preserved via overlap. The `chunk_index` ordering enables the embed_node to process them in sequence and resume from any point on retry.

---

## 📖 Key Terms Glossary

| Term | Plain English |
|------|--------------|
| **Token** | A subword unit used by language models — roughly 3/4 of a word on average |
| **Context window** | The maximum amount of text a model can process at once |
| **Tokenizer** | A function that converts text to tokens — must match the model you're using |
| **Semantic chunking** | Splitting at natural boundaries (sentences, paragraphs) vs. fixed character counts |
| **Overlap** | Intentionally repeating the end of one chunk at the start of the next to preserve boundary context |
| **cl100k_base** | The tokenizer used by text-embedding-3-small and GPT-4o |
| **RAG** | Retrieval-Augmented Generation — find relevant chunks, give them to the AI as context |
| **Greedy packing** | Fill the buffer as much as possible before flushing — maximize chunk size without going over |
