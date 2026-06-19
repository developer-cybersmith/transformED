export interface LearningPulse {
    streak: number;
    hoursThisWeek: number;
    strongestTopic: string;
}

export interface MasteryScore {
    topic: string;
    score: number; // 0-100
}

export interface FocusScore {
    averageFocusDurationMinutes: number;
    focusQuality: 'Excellent' | 'Good' | 'Fair' | 'Poor';
}

export interface ConceptCompletion {
    concept: string;
    completed: boolean;
    lastStudied: string;
}

export interface MockReports {
    pulse: LearningPulse;
    masteryScores: MasteryScore[];
    focus: FocusScore;
    studyTimeBreakdown: { date: string; hours: number }[];
    concepts: ConceptCompletion[];
}

export const mockReports: MockReports = {
    pulse: {
        streak: 5,
        hoursThisWeek: 4.2,
        strongestTopic: "Web Security"
    },
    masteryScores: [
        { topic: "Database Security", score: 85 },
        { topic: "Authentication Systems", score: 92 },
        { topic: "Network Protocols", score: 78 }
    ],
    focus: {
        averageFocusDurationMinutes: 45,
        focusQuality: 'Good'
    },
    studyTimeBreakdown: [
        { date: "2026-06-12", hours: 1.5 },
        { date: "2026-06-13", hours: 0 },
        { date: "2026-06-14", hours: 2.1 },
        { date: "2026-06-15", hours: 0.6 },
        { date: "2026-06-16", hours: 0 }
    ],
    concepts: [
        { concept: "SQL Injection", completed: true, lastStudied: "2026-06-12T10:00:00Z" },
        { concept: "OAuth 2.0", completed: true, lastStudied: "2026-06-14T15:30:00Z" },
        { concept: "Buffer Overflow", completed: false, lastStudied: "2026-06-15T09:15:00Z" }
    ]
};
