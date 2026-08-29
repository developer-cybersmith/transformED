// 20-question Learner DNA onboarding diagnostic.
// Content reviewed/approved — do not edit question text, option text, or IDs.
// See docs/stories/3-4-onboarding-diagnostic-content.md.

export type Dimension = 'cognitive' | 'emotional' | 'self_direction';

export interface Question {
    id: string;
    dimension: Dimension;
    text: string;
    options: string[];
}

export const QUESTIONS: Question[] = [
    // Cognitive — 8
    { id: 'c1', dimension: 'cognitive', text: 'When learning something new, I prefer to:', options: ['See the big picture first, then details', 'Start with specific examples, then generalise', 'Work through step-by-step instructions', 'Discover patterns on my own'] },
    { id: 'c2', dimension: 'cognitive', text: 'I understand abstract concepts best when they are:', options: ['Explained with diagrams or visuals', 'Explained with real-world analogies', 'Broken into numbered steps', 'Linked to prior knowledge I already have'] },
    { id: 'c3', dimension: 'cognitive', text: 'When I encounter a difficult problem, I typically:', options: ['Break it into smaller sub-problems', 'Look for a similar problem I\'ve solved before', 'Think about it holistically before diving in', 'Try different approaches until one works'] },
    { id: 'c4', dimension: 'cognitive', text: 'When studying new material, how quickly do you typically grasp the core idea?', options: ['Immediately — I connect it to what I know within the first pass', 'After one full reading or explanation', 'After a second pass or worked example', 'Only after practising with it multiple times'] },
    { id: 'c5', dimension: 'cognitive', text: 'How do you best retain new information?', options: ['Making notes in my own words', 'Connecting it to a story or narrative', 'Repetition and practice', 'Teaching it to someone else'] },
    { id: 'c6', dimension: 'cognitive', text: 'When reading technical text, I prefer:', options: ['Dense, detailed explanations', 'Concise summaries with key points', 'Examples and code/math alongside theory', 'Narrative writing with minimal jargon'] },
    { id: 'c7', dimension: 'cognitive', text: 'How comfortable are you with ambiguity while learning?', options: ['Very comfortable — I work well with open-ended problems', 'Somewhat comfortable', 'I prefer clear answers but can tolerate some uncertainty', 'I strongly prefer clear, definite answers'] },
    { id: 'c8', dimension: 'cognitive', text: 'Which type of quiz question do you find most useful for learning?', options: ['Multiple-choice recall', 'Short written explanation', 'Problem-solving / worked example', 'Real-world application scenario'] },

    // Emotional — 5
    { id: 'e1', dimension: 'emotional', text: 'When I get a wrong answer on a quiz, I feel:', options: ['Indifferent — I focus on the next question', 'Briefly discouraged, then I move on', 'Motivated to understand why', 'Quite frustrated'] },
    { id: 'e2', dimension: 'emotional', text: 'When you repeatedly fail at a difficult topic, you:', options: ['Keep trying with different approaches until I succeed', 'Take a break and return with fresh eyes', 'Lower the difficulty and build up gradually', 'Move on to a different topic and return later (or not at all)'] },
    { id: 'e3', dimension: 'emotional', text: 'When a concept takes significantly longer to understand than you expected, you:', options: ['Stay with it — I know persistence will pay off', 'Feel frustrated but push through', 'Take a break before returning to it', 'Move on and hope it becomes clearer later'] },
    { id: 'e4', dimension: 'emotional', text: 'When I\'m confused by a concept, my first reaction is:', options: ['Curiosity — I want to dig deeper', 'A bit uneasy, but I push through', 'I feel stuck and need a hint', 'Overwhelmed — I\'d rather skip ahead'] },
    { id: 'e5', dimension: 'emotional', text: 'When you\'re stuck on something, your first instinct is to:', options: ['Search for the answer or explanation yourself', 'Ask a classmate, tutor, or AI tool', 'Re-read the material more carefully', 'Take a break and come back to it'] },

    // Self-Direction — 7
    { id: 's1', dimension: 'self_direction', text: 'How often do you set explicit learning goals before studying?', options: ['Always — I make detailed plans', 'Usually', 'Occasionally', 'Rarely or never'] },
    { id: 's2', dimension: 'self_direction', text: 'When given free choice on a topic to study, you:', options: ['Dive in immediately with a structured plan', 'Explore broadly before focusing', 'Wait for specific guidance', 'Prefer to define a clear scope before exploring'] },
    { id: 's3', dimension: 'self_direction', text: 'How do you prefer to pace your lessons?', options: ['I want full control over pacing', 'Guided pacing with ability to override', 'Mostly guided, with occasional choices', 'Fully guided — tell me what comes next'] },
    { id: 's4', dimension: 'self_direction', text: 'When working through a lesson, you prefer:', options: ['To decide the order and depth of topics yourself', 'A recommended path with freedom to skip or dive deeper', 'A set sequence with clear checkpoints', 'To follow exactly what the system suggests'] },
    { id: 's5', dimension: 'self_direction', text: 'I review my own understanding of a topic:', options: ['Regularly, through self-testing', 'Occasionally, when I feel uncertain', 'Rarely — I rely on external tests', 'Almost never'] },
    { id: 's6', dimension: 'self_direction', text: 'When you encounter an interesting topic in a lesson, you typically:', options: ['Follow tangential links and explore further on your own', 'Note it for later but stay on the lesson path', 'Finish the required material first, then explore if time allows', 'Stay focused — extra reading is not something I usually do'] },
    { id: 's7', dimension: 'self_direction', text: 'When you finish a lesson, you typically:', options: ['Check off a to-do and move on', 'Reflect briefly, then move on', 'Immediately review and summarise notes', 'Rarely do anything after finishing'] },
];

export const DIMENSION_LABEL: Record<Dimension, string> = {
    cognitive: 'Cognitive Style',
    emotional: 'Emotional Profile',
    self_direction: 'Self-Direction',
};
