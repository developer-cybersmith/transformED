// 30-question Learner DNA onboarding diagnostic (Story 235 redesign).
// Content sourced verbatim from docs/proposals/source-specs/
// 2026-09-hie-lecture-format-45min-and-onboarding-pack.pdf, Section 4.1.
// Q1-Q20 MCQ, Q21-Q25 one-liner free text, Q26-Q30 true/false.
// Q16-Q20 are the scored Penta-Intelligence questions (backend answer key:
// apps/api/app/modules/assessment/onboarding_questions.py PENTA_SCORING) --
// their option ORDER is the scoring contract (see
// apps/api/tests/unit/test_onboarding_question_ordering.py). Do not reorder
// options for q16-q20 without updating PENTA_SCORING to match.

export type QuestionFormat = 'mcq' | 'one_liner' | 'true_false';

export interface Question {
    id: string;
    format: QuestionFormat;
    text: string;
    /** mcq only */
    options?: string[];
    /** one_liner only */
    placeholder?: string;
}

export const QUESTIONS: Question[] = [
    // ── Part 1 — MCQ (Q1-Q20) ────────────────────────────────────────────────
    {
        id: 'q1',
        format: 'mcq',
        text: 'What is your PRIMARY reason for using the HIE AI Tutor?',
        options: [
            'Crack a competitive exam (JEE / NEET / UPSC / CAT / GRE)',
            'Perform in a job interview or appraisal',
            'Build a project or job-specific skill',
            'Improve academic performance (school / college)',
            'Personal learning & self-transformation',
        ],
    },
    {
        id: 'q2',
        format: 'mcq',
        text: 'How would you rate your current level in your main subject / goal area?',
        options: [
            'Absolute beginner',
            'Elementary',
            'Intermediate',
            'Advanced',
            'Expert refreshing fundamentals',
        ],
    },
    {
        id: 'q3',
        format: 'mcq',
        text: 'Preferred language of instruction:',
        options: [
            'Pure English',
            'Pure mother tongue',
            'Hinglish / code-mixed',
            'English with mother-tongue explanations on demand',
            'Fully adaptive — AI decides',
        ],
    },
    {
        id: 'q4',
        format: 'mcq',
        text: 'Preferred tutor tone:',
        options: [
            'Formal professor',
            'Friendly mentor',
            'Witty / humorous',
            'Drill-sergeant strict',
            'Motivational coach',
        ],
    },
    {
        id: 'q5',
        format: 'mcq',
        text: 'Your current schooling / education level:',
        options: [
            'School (K–12)',
            'Undergraduate',
            'Postgraduate',
            'Working professional',
            'Self-taught / gap year / other',
        ],
    },
    {
        id: 'q6',
        format: 'mcq',
        text: 'When you think deeply about a hard problem, your inner voice speaks in:',
        options: [
            'My mother tongue',
            'English',
            'A mixture of both',
            'Depends on the subject (maths in one, emotions in another)',
        ],
    },
    {
        id: 'q7',
        format: 'mcq',
        text: 'When you write answers in English, you:',
        options: [
            'Think directly in English',
            'Think in mother tongue, then translate',
            'Mix both constantly',
            'I struggle and lose my original thought',
        ],
    },
    {
        id: 'q8',
        format: 'mcq',
        text: 'Before believing or sharing a viral claim, how often do you verify it?',
        options: ['Always', 'Often', 'Sometimes', 'Rarely', 'Never'],
    },
    {
        id: 'q9',
        format: 'mcq',
        text: 'Have you watched Phir Hera Pheri?',
        options: [
            'Multiple times — I can quote it line by line',
            'Once, enjoyed it',
            'Heard of it, never watched',
            'Never heard of it',
            'I don\'t watch comedy films',
        ],
    },
    {
        id: 'q10',
        format: 'mcq',
        text: 'If your AI Tutor roasted you after a silly mistake, you would:',
        options: [
            'Laugh hard and feel MORE motivated',
            'Laugh, but feel slightly hurt',
            'Feel offended and disengage',
            'Quit the session',
            'Roast it back',
        ],
    },
    {
        id: 'q11',
        format: 'mcq',
        text: 'Set your ROAST CEILING (the tutor will never exceed this):',
        options: [
            'Gentle teasing only',
            'Moderate banter',
            'Full roast mode — I can take it',
            'Zero roasting — keep it respectful',
            'Surprise me — adapt to my mood',
        ],
    },
    {
        id: 'q12',
        format: 'mcq',
        text: 'Honestly — how long can you study before your mind first wanders?',
        options: [
            'Under 10 minutes',
            '10–25 minutes',
            '25–50 minutes',
            '50–90 minutes',
            '90+ minutes (deep-work capable)',
        ],
    },
    {
        id: 'q13',
        format: 'mcq',
        text: 'Hours per day on short-video content (reels/shorts):',
        options: ['None', 'Under 30 min', '30–90 min', '1.5–3 hours', '3+ hours'],
    },
    {
        id: 'q14',
        format: 'mcq',
        text: 'Realistic daily learning time you can protect:',
        options: ['Under 30 min', '30–60 min', '1–2 hours', '2–4 hours', '4+ hours'],
    },
    {
        id: 'q15',
        format: 'mcq',
        text: 'Your 5-year vision:',
        options: [
            'Top institution / campus admission',
            'A specific dream job',
            'My own business / startup',
            'Government / public service',
            'Honestly — still figuring it out',
        ],
    },
    // ── Q16-Q20: Penta-Intelligence (scored) — DO NOT REORDER OPTIONS ────────
    {
        id: 'q16',
        format: 'mcq',
        text: 'A bat and ball cost ₹110 total. The bat costs ₹100 more than the ball. The ball costs:',
        options: ['₹10', '₹5', '₹15', '₹1', '₹2.50'],
    },
    {
        id: 'q17',
        format: 'mcq',
        text: 'A close friend snaps at you rudely for no clear reason. Your most likely response:',
        options: [
            'Snap back immediately',
            'Assume they\'re having a bad day and check on them later',
            'Ignore them for days',
            'Confront them aggressively in front of others',
            'Feel hurt but say nothing and overthink',
        ],
    },
    {
        id: 'q18',
        format: 'mcq',
        text: 'You find a wallet with ₹5,000 and an ID card inside. You:',
        options: [
            'Keep the cash — finder\'s luck',
            'Return it and hope for a reward',
            'Return it anonymously',
            'Hand it to the police / authority',
            'Post about it to look good',
        ],
    },
    {
        id: 'q19',
        format: 'mcq',
        text: 'Which of these is a FACT, not an opinion?',
        options: [
            '\'This policy is a disaster\'',
            '\'Everyone knows this is true\'',
            '\'Unemployment rose from 4.1% to 5.3% in the report\'',
            '\'Any fool can see the truth\'',
            '\'Experts agree without question\'',
        ],
    },
    {
        id: 'q20',
        format: 'mcq',
        text: 'When researching an unfamiliar topic, your default method is:',
        options: [
            'First Google result',
            'Wikipedia summary',
            'Compare 3+ independent sources',
            'Go to primary sources / papers',
            'Ask AI and accept the answer',
        ],
    },
    // ── Part 2 — One-Liners (Q21-Q25) ────────────────────────────────────────
    {
        id: 'q21',
        format: 'one_liner',
        text: 'In ONE sentence, describe what you want to achieve in the next 6 months.',
        placeholder: 'In the next 6 months, I want to...',
    },
    {
        id: 'q22',
        format: 'one_liner',
        text: 'Describe one moment when you KNEW the answer in your mother tongue but couldn\'t say it in English.',
        placeholder: 'It happened when...',
    },
    {
        id: 'q23',
        format: 'one_liner',
        text: 'Describe your last true deep-focus session: how long did it last and exactly what broke it?',
        placeholder: 'It lasted about... and it broke when...',
    },
    {
        id: 'q24',
        format: 'one_liner',
        text: 'On your worst, most exhausted day — what would still get you to open the app?',
        placeholder: 'Even on a bad day, I would open it for...',
    },
    {
        id: 'q25',
        format: 'one_liner',
        text: 'Where do you honestly see yourself in 2030?',
        placeholder: 'By 2030, I see myself...',
    },
    // ── Part 3 — True / False (Q26-Q30) ──────────────────────────────────────
    {
        id: 'q26',
        format: 'true_false',
        text: 'I have abandoned at least one online course in the past 12 months.',
    },
    {
        id: 'q27',
        format: 'true_false',
        text: 'I have passed exams mainly by memorising without truly understanding.',
    },
    {
        id: 'q28',
        format: 'true_false',
        text: 'I can watch reels for hours but struggle to read for 10 minutes.',
    },
    {
        id: 'q29',
        format: 'true_false',
        text: 'Being roasted motivates me more than being praised.',
    },
    {
        id: 'q30',
        format: 'true_false',
        text: 'I have shared content online without verifying it first.',
    },
];
