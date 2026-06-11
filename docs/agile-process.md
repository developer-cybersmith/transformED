# Agile Process for AI Application Development

## Why AI Apps Need a Modified Agile

Standard Scrum/Kanban works well for deterministic software. AI features introduce **non-determinism, evaluation overhead, and prompt drift** — so the process needs adjustments.

---

## Core Framework: AI-Augmented Scrum

### Sprint Length
**2-week sprints** — short enough to catch prompt regressions quickly, long enough to build + evaluate an AI feature end-to-end.

---

## Story Types (4 kinds)

| Type | Description | Example |
|------|-------------|---------|
| **Product Story** | User-facing feature with AI component | "As a learner, I can get AI feedback on my essay" |
| **AI Experiment** | Time-boxed spike to evaluate model/approach | "Evaluate GPT-4o vs Claude for quiz generation — 3-day timebox" |
| **Eval Story** | Build or improve evaluation pipeline | "Add automated rubric-scoring eval with 100 golden examples" |
| **Infra Story** | Non-AI engineering work | "Add rate limiting to the AI endpoints" |

---

## Sprint Ceremonies

### Sprint Planning (Day 1, 2 hrs)
- Review PRD / backlog
- Classify each story by type
- For AI Experiments: define the hypothesis and success metric BEFORE starting
- Assign story points (AI stories get +50% buffer for iteration)

### Daily Standup (15 min)
- What did I ship? What eval results came in? Any prompt regression?
- Flag blockers early — LLM output quality issues are blockers

### AI Review (mid-sprint, 30 min)
- Review eval results from any AI experiments or features under development
- Decide: iterate on prompts, change model, or pivot approach?
- Update the prompt version if changed

### Sprint Review (Day 14, 1 hr)
- Demo working features (including AI behavior demos with real outputs)
- Review eval metrics vs. baseline — did AI quality improve or regress?
- Update the eval golden set with new examples

### Retrospective (Day 14, 45 min)
- What worked? What didn't?
- Specific AI retro questions: prompt quality, model costs, latency, hallucination rate

---

## Definition of Done (AI Features)

A story is NOT done until:
- [ ] Feature works end-to-end in staging
- [ ] Automated evals pass (accuracy >= threshold defined in story)
- [ ] Prompt is versioned and committed to `packages/ai/prompts/`
- [ ] LLM cost per request is measured and within budget
- [ ] Edge cases tested: empty input, adversarial input, max-length input
- [ ] Latency measured (P50, P95)
- [ ] Unit tests pass
- [ ] PR reviewed and merged

---

## Backlog Structure

```
Epics (6-12 weeks)
  └── Features (2-4 weeks)
        └── Stories (fits in 1 sprint)
              └── Tasks (1-2 days each)
```

### Epic Examples for EdTech AI Platform
1. **Personalized Learning Engine** — adaptive content, learner modeling
2. **AI Assessment & Feedback** — quiz generation, essay scoring, rubric-based feedback
3. **Content Authoring AI** — course creation assistant, slide generation
4. **Analytics & Insights** — learning outcome prediction, engagement scoring
5. **Platform Core** — auth, billing, onboarding, notifications

---

## AI-Specific Practices

### Prompt Versioning
- Every prompt gets a semantic version (`v1.0.0`)
- Breaking changes to prompt structure = major version bump
- Track prompt versions in eval results so you can correlate quality changes

### Evaluation-Driven Development (EDD)
1. Define success metric BEFORE building the AI feature
2. Create golden dataset (50-200 labeled examples)
3. Run evals on every PR that touches prompts
4. Never ship if eval score drops below baseline

### Model Selection Policy
| Use case | Model | Rationale |
|----------|-------|-----------|
| Essay feedback, complex reasoning | `claude-opus-4-8` | Highest quality |
| Tutoring chat, quiz generation | `claude-sonnet-4-6` | Quality + speed balance |
| Grading hints, short completions | `claude-haiku-4-5-20251001` | Low latency, low cost |

### Cost Guardrails
- Set per-user monthly token budget
- Alert at 80% of budget
- Hard-stop at 100% (degrade gracefully to cached/static responses)

---

## Tools & Integrations

| Tool | Purpose |
|------|---------|
| GitHub Projects | Backlog, sprint board |
| GitHub Actions | CI/CD + automated eval runs |
| Langfuse / Braintrust | LLM observability, eval tracking |
| Sentry | Error monitoring |
| Vercel Analytics | Frontend performance |
| Supabase | DB + auth + storage |

---

## PRD → Sprint Flow

```
PRD provided
    ↓
Break into Epics (product lead)
    ↓
Epics → Features → Stories (tech lead + product)
    ↓
Stories refined with AI experiment hypotheses
    ↓
Sprint planning: pick stories that fit 2 weeks
    ↓
Build → Eval → Review → Ship
    ↓
Retrospective → update process
```
