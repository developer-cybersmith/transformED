export interface UserProfile {
    id: string;
    name: string;
    email: string;
    learningGoal: string;
    academicFocus: string;
}

export interface LearningPreferences {
    pace: 'relaxed' | 'moderate' | 'accelerated';
    interventionFrequency: 'low' | 'medium' | 'high';
    explanationStyle: 'concise' | 'detailed' | 'socratic';
    learningStyle: 'visual' | 'auditory' | 'kinesthetic' | 'reading';
}

export interface NotificationSettings {
    lessonReady: boolean;
    weeklyProgress: boolean;
    streakReminders: boolean;
}

// UI-only mock preferences. NOT the DPDP attention-tracking consent record —
// that is tracked separately via the real `user_consents` table (see
// supabase/migrations/20260702000000_dpdp_user_consents.sql and CLAUDE.md
// §18). `focusDetection` here is a display preference for whether the toggle
// shows on, not an authoritative consent grant.
export interface PrivacySettings {
    focusDetection: boolean;
    learningAnalytics: boolean;
    personalizedRecommendations: boolean;
}

export interface MockUser {
    profile: UserProfile;
    preferences: LearningPreferences;
    notifications: NotificationSettings;
    privacy: PrivacySettings;
}

export const mockUser: MockUser = {
    profile: {
        id: "usr_12345",
        name: "J. Robert Oppenheimer",
        email: "robert@example.com",
        learningGoal: "Master Advanced Physics & Theoretical Foundations",
        academicFocus: "Quantum Mechanics",
    },
    preferences: {
        pace: "accelerated",
        interventionFrequency: "medium",
        explanationStyle: "socratic",
        learningStyle: "visual"
    },
    notifications: {
        lessonReady: true,
        weeklyProgress: true,
        streakReminders: false
    },
    privacy: {
        focusDetection: true,
        learningAnalytics: true,
        personalizedRecommendations: true
    }
};
