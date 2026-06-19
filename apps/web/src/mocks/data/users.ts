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

export interface MockUser {
    profile: UserProfile;
    preferences: LearningPreferences;
    notifications: NotificationSettings;
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
    }
};
