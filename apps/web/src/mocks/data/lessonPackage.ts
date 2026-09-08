import type { LessonPackage } from '@hie/shared/types/lesson';

export const mockLessonPackage: LessonPackage = {
  lesson_id: 'lesson_mock_1',
  book_id: 'book_1',
  chapter_id: 'chap_1',
  created_at: '2026-06-26T00:00:00Z',
  metadata: {
    title: 'SQL Injection — How Attackers Break In',
    subject: 'Web Security',
    total_segments: 2,
    estimated_duration_mins: 5,
    complexity_level: 'medium',
    tier: 'T2',
  },
  segments: [
    {
      segment_id: 'seg_0',
      segment_index: 0,
      title: 'What is SQL Injection?',
      summary:
        'Learn how SQL injection works by watching a live attack on a vulnerable login form using a quote character to trigger a SQL syntax error.',
      complexity: {
        level: 'medium',
        cognitive_load: 'medium',
        abstraction_level: 'concrete',
        prerequisite_concepts: ['basic SQL SELECT/WHERE', 'how login forms work'],
        narration_style: 'explanatory',
        quiz_difficulty: 'medium',
        intervention_sensitivity: 0.4,
      },
      slides: [
        {
          slide_id: 'sl_0_0',
          // 0:00 – 0:35 of the audio (intro + password guess attempt)
          title: 'What is SQL Injection?',
          bullets: [
            'SQL injection is one of the most common attack methods on the web',
            'Attackers insert malicious SQL code through form inputs',
            "First attempt: guessing the password — doesn't work",
          ],
          image_url: null,
          fallback_image_url: null,
        },
        {
          slide_id: 'sl_0_1',
          // 0:35 – 1:32 of the audio (quote char → crash → code reveal)
          title: 'The Quote Character Crash',
          bullets: [
            "Adding a trailing quote character crashes the application",
            'The app logs show a SQL syntax error — the query broke',
            "The quote is inserted directly into the SQL string and terminates it early",
            'This proves the input is not sanitised — the app is vulnerable',
          ],
          image_url: null,
          fallback_image_url: null,
        },
      ],
      narration: {
        script:
          "Welcome to the Hacksplaining video tutorial series. In this video, we will learn about SQL injection. First, let's try guessing the password — that didn't work. Now let's add a quote character. The application crashed with an SQL syntax error. This is what the code looks like behind the scenes — the quote is inserted directly into the SQL string and terminates the query early.",
        audio_url: '/What-Is-SQL-Injection.mp3',
        audio_provider: 'azure',
        timestamps: [
          { slide_id: 'sl_0_0', start_ms: 0,     end_ms: 35000 },
          { slide_id: 'sl_0_1', start_ms: 35000,  end_ms: 92000 },
        ],
      },
      quiz: [
        {
          question_id: 'q_0_0',
          type: 'mcq',
          question:
            'What does a SQL syntax error in the login logs indicate about the application?',
          options: [
            'The server ran out of memory',
            "The user's password is incorrect",
            'User input is being inserted directly into a SQL query without sanitisation',
            'The database connection timed out',
          ],
          correct_index: 2,
          explanation:
            "A SQL syntax error triggered by a quote character in a login form means the input is concatenated directly into a SQL query — a classic sign of SQL injection vulnerability.",
          difficulty: 'medium',
        },
      ],
      teachback_prompt:
        'Explain in your own words: why does adding a single quote character to a login field crash a vulnerable application? What does the error reveal about how the application is built?',
      jargon: [
        {
          term: 'SQL Injection',
          definition:
            'An attack where malicious SQL code is inserted into an input field, manipulating the database query the server runs.',
        },
        {
          term: 'SQL Syntax Error',
          definition:
            'An error thrown when a SQL statement is malformed — often caused by an unescaped special character like a quote in user input.',
        },
      ],
      interventions: {
        distraction: [
          "Stay focused — the next part shows exactly how the attack succeeds. You'll want to see this.",
          "Quick check-in: are you still with me? The quote character trick is the key insight here.",
          "Almost through Part 1. Stick with it — the bypass technique coming next is the payoff.",
        ],
        confusion: [
          "The core idea: when a quote from user input breaks the SQL query structure, the attacker controls the query.",
          "Think of it like this — the app is building a sentence using your input. A quote character ends the sentence early and lets an attacker write the rest.",
          "Let's recap: vulnerable apps paste your input straight into SQL. A quote breaks the syntax. That error is the red flag.",
        ],
        fatigue: [
          "You've been at this for a bit. Take a 2-minute break and come back fresh for the attack demo.",
          "Short break? The bypass technique in Part 2 is worth seeing clearly.",
          "Listen to your body — a quick stretch now means better focus for the final segment.",
        ],
      },
    },
    {
      segment_id: 'seg_1',
      segment_index: 1,
      title: 'Bypassing Authentication & Prevention',
      summary:
        'See a complete SQL injection bypass using the double-dash comment trick, and learn why parameterised queries stop the attack cold.',
      complexity: {
        level: 'medium',
        cognitive_load: 'high',
        abstraction_level: 'conceptual',
        prerequisite_concepts: ['SQL injection basics', 'SQL syntax error'],
        narration_style: 'explanatory',
        quiz_difficulty: 'medium',
        intervention_sensitivity: 0.5,
      },
      slides: [
        {
          slide_id: 'sl_1_0',
          // Maps to 1:32 – 2:10 of audio (crafted password → access granted)
          title: 'The Double-Dash Bypass',
          bullets: [
            "A Double-Dash Comment (--) tells the database to ignore everything after it",
            "The attacker appends -- to their input, cutting off the password check",
            "We gained access without knowing the correct credentials",
            "The database never verifies the real password — authentication is bypassed",
          ],
          image_url: null,
          fallback_image_url: null,
        },
        {
          slide_id: 'sl_1_1',
          // Maps to 2:10 – 2:38 of audio (prevention + conclusion)
          title: 'Preventing SQL Injection',
          bullets: [
            'SQL Injection is one of the most prevalent vulnerabilities on the internet',
            'Always use a Parameterised Query — never concatenate user input into SQL',
            'If you fix only one vulnerability this year, fix SQL Injection first',
          ],
          image_url: null,
          fallback_image_url: null,
        },
      ],
      narration: {
        script:
          "Now let's try a specifically crafted password — and we're in. The double dashes caused the database to ignore the rest of the SQL statement, so we were authenticated without the real password. SQL injection is one of the most prevalent vulnerabilities on the internet. Use parameterised queries to protect yourself.",
        audio_url: '/What-Is-SQL-Injection.mp3',
        audio_provider: 'azure',
        timestamps: [
          // Relative to segment audio start (same file replays from 0ms for testing)
          // Quiz fires at 148s — leaves ~10s of audio after teach-back before handleEnded fires
          { slide_id: 'sl_1_0', start_ms: 0,      end_ms: 74000  },
          { slide_id: 'sl_1_1', start_ms: 74000,  end_ms: 148000 },
        ],
      },
      quiz: [
        {
          question_id: 'q_1_0',
          type: 'mcq',
          question:
            'Why does entering `-- ` (double dash) in a password field bypass SQL authentication?',
          options: [
            'It encrypts the password before sending it',
            'It triggers a server-side admin override',
            'It comments out the rest of the SQL query, skipping the password check',
            'It causes a timeout that auto-approves the login',
          ],
          correct_index: 2,
          explanation:
            '`--` is the SQL single-line comment syntax. When injected into the query, it causes the database to ignore everything after it — including the password comparison — so the attacker is authenticated without valid credentials.',
          difficulty: 'medium',
        },
      ],
      teachback_prompt:
        "Explain the double-dash SQL injection attack: what does `--` do in SQL, why does it bypass a password check, and what is the correct fix a developer should apply?",
      jargon: [
        {
          term: 'Double-Dash Comment',
          definition:
            'In SQL, `--` marks the start of a single-line comment. Everything after it on the same line is ignored by the database engine.',
        },
        {
          term: 'Parameterised Query',
          definition:
            'A SQL query where user input is passed as a separate parameter, never concatenated into the query string — completely preventing SQL injection.',
        },
      ],
      interventions: {
        distraction: [
          "This is the most important part — the actual attack and the fix. Stay focused.",
          "The double-dash trick is what most SQL injection attacks in the real world use. Don't miss this.",
          "Last stretch. The prevention advice here is what you'll carry into your own projects.",
        ],
        confusion: [
          "The key: `--` tells the database 'ignore everything after this line'. The attacker uses it to erase the password check.",
          "Think of `--` as a pair of scissors that cuts the query in half. The attacker controls where the cut happens.",
          "To prevent this: never build SQL strings by concatenating input. Use `?` placeholders in prepared statements instead.",
        ],
        fatigue: [
          "This is the final segment. The fix is simple once you see the attack — push through.",
          "Almost done. The parameterised query concept coming up is the single most valuable thing to take from this lesson.",
          "You've made it to the last slide. One more minute and you've completed the lesson.",
        ],
      },
    },
  ],
  glossary: [
    {
      term: 'SQL Injection',
      definition:
        'An attack technique where malicious SQL statements are inserted into a login form or other input field, allowing attackers to manipulate the database query.',
    },
    {
      term: 'SQL Syntax Error',
      definition:
        'An error thrown by the database when a SQL statement is malformed. In a vulnerable app, triggering this with a quote character reveals the injection point.',
    },
    {
      term: 'Double-Dash Comment',
      definition:
        'The `--` sequence in SQL begins a single-line comment, causing the database to ignore everything that follows on that line.',
    },
    {
      term: 'Parameterised Query',
      definition:
        'A prepared SQL statement that treats user input as a data value, never as executable SQL. The correct defence against SQL injection.',
    },
    {
      term: 'Authentication Bypass',
      definition:
        'Gaining access to a system without valid credentials, typically by exploiting a vulnerability in the login logic.',
    },
  ],
};
