import type { LessonPackage } from '@hie/shared/types/lesson';

export const mockLessonPackage: LessonPackage = {
  lesson_id: 'lesson_mock_1',
  book_id: 'book_1',
  chapter_id: 'chap_1',
  created_at: '2026-06-26T00:00:00Z',
  metadata: {
    title: 'Introduction to Artificial Intelligence',
    subject: 'Computer Science',
    total_segments: 2,
    estimated_duration_mins: 15,
    complexity_level: 'medium',
  },
  segments: [
    {
      segment_id: 'seg_0',
      segment_index: 0,
      title: 'What is AI?',
      summary: 'Introduction to artificial intelligence concepts and history.',
      complexity: {
        level: 'low',
        cognitive_load: 'low',
        abstraction_level: 'concrete',
        prerequisite_concepts: [],
        narration_style: 'explanatory',
        quiz_difficulty: 'easy',
        intervention_sensitivity: 0.3,
      },
      slides: [
        {
          slide_id: 'sl_0_0',
          title: 'Defining AI',
          bullets: ['AI simulates human intelligence', 'First coined in 1956', 'Broad field with many subdomains'],
          image_url: null,
          fallback_image_url: null,
        },
        {
          slide_id: 'sl_0_1',
          title: 'Types of AI',
          bullets: ['Narrow AI: task-specific systems', 'General AI: human-level reasoning (theoretical)', 'Superintelligence: beyond human ability'],
          image_url: null,
          fallback_image_url: null,
        },
      ],
      narration: {
        script: 'Artificial intelligence is the simulation of human intelligence processes by computer systems.',
        audio_url: 'https://cdn.hie.ai/mock/seg_0.mp3',
        audio_provider: 'azure',
        timestamps: [
          { slide_id: 'sl_0_0', start_ms: 0, end_ms: 15000 },
          { slide_id: 'sl_0_1', start_ms: 15000, end_ms: 30000 },
        ],
      },
      quiz: [
        {
          question_id: 'q_0_0',
          type: 'mcq',
          question: 'What year was the term "Artificial Intelligence" first coined?',
          options: ['1945', '1950', '1956', '1969'],
          correct_index: 2,
          explanation: 'The term "Artificial Intelligence" was coined by John McCarthy in 1956 at the Dartmouth Conference.',
          difficulty: 'easy',
        },
      ],
      teachback_prompt: 'Explain what Artificial Intelligence is in your own words, and give one example of a narrow AI system you use today.',
      jargon: [
        { term: 'Narrow AI', definition: 'An AI system designed to perform a specific task, like image recognition or language translation.' },
      ],
      interventions: {
        distraction: [
          "It looks like you might be distracted. Let's refocus — this concept is foundational.",
          "Quick check-in: are you still with me? Take a deep breath and let's continue.",
          "Stay focused — you're almost through this segment. You've got this.",
        ],
        confusion: [
          "Seems like this might be confusing. The key idea is that AI mimics human thinking using data and algorithms.",
          "Don't worry if this feels abstract at first. It will make more sense as we see real examples.",
          "Let's recap: AI is about making machines perform tasks that normally require human intelligence.",
        ],
        fatigue: [
          "You've been studying for a while. Take a 2-minute break if you need it — then come back refreshed.",
          "Your focus is dipping. A quick stretch will reset your attention.",
          "Listen to your body — short breaks improve retention. Resume when you're ready.",
        ],
      },
    },
    {
      segment_id: 'seg_1',
      segment_index: 1,
      title: 'Machine Learning Basics',
      summary: 'How machines learn from data to make predictions.',
      complexity: {
        level: 'medium',
        cognitive_load: 'medium',
        abstraction_level: 'conceptual',
        prerequisite_concepts: ['What is AI?'],
        narration_style: 'explanatory',
        quiz_difficulty: 'medium',
        intervention_sensitivity: 0.5,
      },
      slides: [
        {
          slide_id: 'sl_1_0',
          title: 'What is Machine Learning?',
          bullets: ['ML is a subset of AI', 'Systems learn from data, not explicit rules', 'Three types: supervised, unsupervised, reinforcement'],
          image_url: null,
          fallback_image_url: null,
        },
        {
          slide_id: 'sl_1_1',
          title: 'How Learning Works',
          bullets: ['Input data → Model training → Predictions', 'More data = better accuracy', 'Models improve over time'],
          image_url: null,
          fallback_image_url: null,
        },
      ],
      narration: {
        script: 'Machine learning is a subset of artificial intelligence that enables systems to learn from data.',
        audio_url: 'https://cdn.hie.ai/mock/seg_1.mp3',
        audio_provider: 'azure',
        timestamps: [
          { slide_id: 'sl_1_0', start_ms: 0, end_ms: 15000 },
          { slide_id: 'sl_1_1', start_ms: 15000, end_ms: 30000 },
        ],
      },
      quiz: [
        {
          question_id: 'q_1_0',
          type: 'mcq',
          question: 'Which of the following best describes machine learning?',
          options: [
            'Programming a computer with explicit rules for every situation',
            'Training a system to learn patterns from data',
            'Connecting a computer to the internet',
            'Using a calculator for complex math',
          ],
          correct_index: 1,
          explanation: 'Machine learning trains systems to identify patterns in data, rather than following pre-programmed rules.',
          difficulty: 'medium',
        },
      ],
      teachback_prompt: 'Explain the difference between traditional programming and machine learning. Use an example from your daily life.',
      jargon: [
        { term: 'Supervised Learning', definition: 'Training a model on labelled data where the correct answers are provided.' },
        { term: 'Unsupervised Learning', definition: 'Training a model on unlabelled data to find hidden patterns.' },
      ],
      interventions: {
        distraction: [
          "Looks like your attention drifted. This segment covers how machines actually learn — the heart of modern AI.",
          "Let's refocus. Machine learning is one of the most in-demand skills in tech right now.",
          "Almost there. Refocus for the final minutes of this segment.",
        ],
        confusion: [
          "If the learning types are confusing, just remember: supervised = teacher helps, unsupervised = figure it out alone.",
          "Take your time with this. The training loop concept clicks for most learners on the second example.",
          "Let's slow down: data goes in, the model finds patterns, predictions come out. That's the core loop.",
        ],
        fatigue: [
          "This is the last segment. You're almost at the quiz — push through and you'll have completed the lesson!",
          "Nearly there. One more concept and you're done.",
          "Your effort is paying off. Stay with it for just a few more minutes.",
        ],
      },
    },
  ],
  glossary: [
    { term: 'Artificial Intelligence', definition: 'The simulation of human intelligence processes by computer systems.' },
    { term: 'Machine Learning', definition: 'A subset of AI where systems learn from data rather than explicit programming.' },
    { term: 'Algorithm', definition: 'A set of rules or instructions that a computer follows to solve a problem.' },
  ],
};
