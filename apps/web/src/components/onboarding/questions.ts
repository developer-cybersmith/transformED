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
    { id: 'c4', dimension: 'cognitive', text: 'My attention span during focused study is roughly:', options: ['Less than 15 minutes', '15–30 minutes', '30–45 minutes', 'More than 45 minutes'] },
    { id: 'c5', dimension: 'cognitive', text: 'How do you best retain new information?', options: ['Repetition and practice', 'Teaching it to someone else', 'Making notes in my own words', 'Connecting it to a story or narrative'] },
    { id: 'c6', dimension: 'cognitive', text: 'When reading technical text, I prefer:', options: ['Dense, detailed explanations', 'Concise summaries with key points', 'Examples and code/math alongside theory', 'Narrative writing with minimal jargon'] },
    { id: 'c7', dimension: 'cognitive', text: 'How comfortable are you with ambiguity while learning?', options: ['Very comfortable — I enjoy open-ended exploration', 'Somewhat comfortable', 'I prefer clear answers but can tolerate some uncertainty', 'I strongly prefer clear, definite answers'] },
    { id: 'c8', dimension: 'cognitive', text: 'Which type of quiz question do you find most useful for learning?', options: ['Multiple-choice recall', 'Short written explanation', 'Problem-solving / worked example', 'Real-world application scenario'] },

    // Emotional — 5
    { id: 'e1', dimension: 'emotional', text: 'When I get a wrong answer on a quiz, I feel:', options: ['Motivated to understand why', 'Briefly discouraged, then I move on', 'Quite frustrated', 'Indifferent — I focus on the next question'] },
    { id: 'e2', dimension: 'emotional', text: 'Praise and encouragement during study:', options: ['Significantly boosts my motivation', 'Helps somewhat', 'Makes little difference to me', 'Can feel patronising — I prefer neutral feedback'] },
    { id: 'e3', dimension: 'emotional', text: 'How does time pressure (e.g. timed quizzes) affect you?', options: ['I perform better under pressure', 'It slightly stresses me but I manage', 'It significantly impairs my thinking', 'I strongly dislike it and avoid it'] },
    { id: 'e4', dimension: 'emotional', text: 'When I\'m confused by a concept, my first reaction is:', options: ['Curiosity — I want to dig deeper', 'Mild anxiety, but I push through', 'I feel stuck and need a hint', 'I feel anxious and want to move on'] },
    { id: 'e5', dimension: 'emotional', text: 'How do you feel about having an AI track your engagement during learning?', options: ['Excited — I want personalised help', 'Fine, as long as my privacy is protected', 'Slightly uncomfortable but willing to try', 'I would prefer to opt out'] },

    // Self-Direction — 7
    { id: 's1', dimension: 'self_direction', text: 'How often do you set explicit learning goals before studying?', options: ['Always — I make detailed plans', 'Usually', 'Occasionally', 'Rarely or never'] },
    { id: 's2', dimension: 'self_direction', text: 'When given free choice on a topic to study, you:', options: ['Dive in immediately with a structured plan', 'Explore broadly before focusing', 'Wait for specific guidance', 'Feel overwhelmed and delay starting'] },
    { id: 's3', dimension: 'self_direction', text: 'How do you prefer to pace your lessons?', options: ['I want full control over pacing', 'Guided pacing with ability to override', 'Mostly guided, with occasional choices', 'Fully guided — tell me what comes next'] },
    { id: 's4', dimension: 'self_direction', text: 'How do you typically respond to a learning setback?', options: ['I analyse what went wrong and adjust', 'I take a short break then retry', 'I ask for help or hints', 'I often give up on that topic for now'] },
    { id: 's5', dimension: 'self_direction', text: 'I review my own understanding of a topic:', options: ['Regularly, through self-testing', 'Occasionally, when I feel uncertain', 'Rarely — I rely on external tests', 'Almost never'] },
    { id: 's6', dimension: 'self_direction', text: 'Which best describes your study consistency?', options: ['I study every day at fixed times', 'I study most days, flexible schedule', 'I study in bursts when motivated', 'I study primarily close to deadlines'] },
    { id: 's7', dimension: 'self_direction', text: 'When you finish a lesson, you typically:', options: ['Immediately review and summarise notes', 'Reflect briefly, then move on', 'Check off a to-do and move on', 'Rarely do anything after finishing'] },
];

export const DIMENSION_LABEL: Record<Dimension, string> = {
    cognitive: 'Cognitive Style',
    emotional: 'Emotional Profile',
    self_direction: 'Self-Direction',
};
