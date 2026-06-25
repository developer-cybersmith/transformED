export type LessonStatus = 'completed' | 'in_progress' | 'processing' | 'failed';

export interface Slide {
    id: string;
    title: string;
    content: string;
    startTimestamp: number;
    endTimestamp: number;
}

export type TimelineEventType = 'slide_change' | 'quiz' | 'teachback' | 'intervention' | 'pause';

export interface BaseTimelineEvent {
    id: string;
    type: TimelineEventType;
    timestamp: number;
}

export interface SlideChangeEvent extends BaseTimelineEvent {
    type: 'slide_change';
    slideId: string;
}

export interface QuizEvent extends BaseTimelineEvent {
    type: 'quiz';
    question: string;
    options: string[];
    correctOptionIndex: number;
}

export interface TeachbackEvent extends BaseTimelineEvent {
    type: 'teachback';
    prompt: string;
}

export interface InterventionEvent extends BaseTimelineEvent {
    type: 'intervention';
    trigger: string;
    message: string;
}

export type TimelineEvent = SlideChangeEvent | QuizEvent | TeachbackEvent | InterventionEvent;

export interface MockLesson {
    id: string;
    title: string;
    chapterTitle: string;
    durationSeconds: number;
    status: LessonStatus;
    progressPercent: number;
    lastAccessed: string;
    slides: Slide[];
    timeline: TimelineEvent[];
}

export const mockLessons: MockLesson[] = [
    {
        id: "les_1",
        title: "SQL Injection Vectors",
        chapterTitle: "Chapter 3: Database Security",
        durationSeconds: 1500, // 25 mins
        status: "in_progress",
        progressPercent: 72,
        lastAccessed: new Date(Date.now() - 1000 * 60 * 60).toISOString(),
        slides: [
            {
                id: "slide_1",
                title: "What is SQL Injection?",
                content: "SQL injection is a code injection technique that might destroy your database.",
                startTimestamp: 0,
                endTimestamp: 300
            },
            {
                id: "slide_2",
                title: "Common Attack Vectors",
                content: "Attackers look for unsanitized inputs in web forms, APIs, and URL parameters.",
                startTimestamp: 300,
                endTimestamp: 600
            }
        ],
        timeline: [
            { id: "tl_1", type: "slide_change", timestamp: 0, slideId: "slide_1" },
            { id: "tl_2", type: "slide_change", timestamp: 15, slideId: "slide_2" },
            {
                id: "tl_3",
                type: "quiz",
                timestamp: 30,
                question: "Which SQL clause is commonly abused during SQL Injection?",
                options: ["SELECT", "WHERE", "JOIN", "FROM"],
                correctOptionIndex: 1
            },
            {
                id: "tl_4",
                type: "intervention",
                timestamp: 45,
                trigger: "passive_learning_detected",
                message: "Before moving on, explain the core concept in your own words."
            }
        ]
    },
    {
        id: "les_2",
        title: "Authentication vs Authorization",
        chapterTitle: "Chapter 1: Identity Management",
        durationSeconds: 1200,
        status: "completed",
        progressPercent: 100,
        lastAccessed: new Date(Date.now() - 1000 * 60 * 60 * 24).toISOString(),
        slides: [
            {
                id: "slide_1",
                title: "Authentication",
                content: "Verifying who a user is (e.g., passwords, biometrics).",
                startTimestamp: 0,
                endTimestamp: 600
            },
            {
                id: "slide_2",
                title: "Authorization",
                content: "Verifying what they have access to do (e.g., RBAC, ABAC).",
                startTimestamp: 600,
                endTimestamp: 1200
            }
        ],
        timeline: [
            { id: "tl_1", type: "slide_change", timestamp: 0, slideId: "slide_1" },
            {
                id: "tl_2",
                type: "teachback",
                timestamp: 20,
                prompt: "Explain the difference between authentication and authorization in your own words."
            },
            { id: "tl_3", type: "slide_change", timestamp: 40, slideId: "slide_2" }
        ]
    },
    {
        id: "les_3",
        title: "Introduction to Neural Networks",
        chapterTitle: "Chapter 1: Machine Learning Fundamentals",
        durationSeconds: 1800,
        status: "processing",
        progressPercent: 0,
        lastAccessed: new Date().toISOString(),
        slides: [],
        timeline: []
    },
    {
        id: "les_4",
        title: "Buffer Overflows",
        chapterTitle: "Chapter 4: Operating Systems",
        durationSeconds: 2400,
        status: "failed",
        progressPercent: 0,
        lastAccessed: new Date().toISOString(),
        slides: [],
        timeline: []
    },
    {
        id: "les_5",
        title: "Zero Trust Architecture",
        chapterTitle: "Chapter 5: Network Security",
        durationSeconds: 1100,
        status: "in_progress",
        progressPercent: 15,
        lastAccessed: new Date(Date.now() - 1000 * 60 * 15).toISOString(),
        slides: [],
        timeline: []
    }
];
