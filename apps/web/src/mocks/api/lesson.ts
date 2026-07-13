import { randomDelay, delay } from '../utils/delay';
import { createSuccessResponse, createErrorResponse, ApiResponse } from '../utils/response';
import { mockLessons, MockLesson } from '../data/lessons';
import { mockLessonPackage } from '../data/lessonPackage';
import type { LessonPackage } from '@hie/shared/types/lesson';

export const getLessonById = async (lessonId: string): Promise<ApiResponse<MockLesson>> => {
    // Simulate 800ms - 1500ms latency for fetching large lesson package
    await randomDelay(800, 1500);

    let lesson = mockLessons.find(l => l.id === lessonId);

    if (!lesson) {
        if (lessonId.startsWith('lesson_')) {
            // Dynamically serve a completed lesson payload for the Upload flow tests
            lesson = {
                id: lessonId,
                title: "Synthesized Document Module",
                chapterTitle: "Dynamic Upload Processing",
                durationSeconds: 1500,
                status: 'in_progress',
                progressPercent: 0,
                lastAccessed: new Date().toISOString(),
                thumbnailUrl: "https://images.unsplash.com/photo-1555949963-aa79dcee981c?auto=format&fit=crop&q=80&w=600&h=400",
                slides: [
                    {
                        id: "slide_1",
                        title: "Document Synthesis Complete",
                        content: "We have successfully processed your uploaded PDF and structured it into a logical journey. The AI has extracted key concepts and generated auditory narrative scripts.",
                        startTimestamp: 0,
                        endTimestamp: 300
                    },
                    {
                        id: "slide_2",
                        title: "Core Findings",
                        content: "This material primarily focuses on deeply interconnected concepts. As you proceed, we'll prompt you with Teachback modules to verify understanding.",
                        startTimestamp: 300,
                        endTimestamp: 600
                    }
                ],
                timeline: [
                    { id: "tl_1", type: "slide_change", timestamp: 0, slideId: "slide_1" },
                    { id: "tl_2", type: "slide_change", timestamp: 10, slideId: "slide_2" },
                    {
                        id: "tl_3",
                        type: "quiz",
                        timestamp: 20,
                        question: "What is the primary mechanism the AI uses to verify your understanding?",
                        options: ["Multiple choice exams", "Teachback modules", "Time limits", "Video responses"],
                        correctOptionIndex: 1
                    }
                ]
            };
            mockLessons.push(lesson);
        } else {
            return createErrorResponse("Lesson not found");
        }
    }

    return createSuccessResponse(lesson, "Lesson retrieved successfully");
};

export const getLessonPackageById = async (lessonId: string): Promise<ApiResponse<LessonPackage>> => {
    await randomDelay(800, 1500);
    const known = mockLessons.find(l => l.id === lessonId);
    if (!known) return createErrorResponse('Lesson not found');
    return createSuccessResponse(
        { ...mockLessonPackage, lesson_id: lessonId },
        'Lesson package retrieved successfully',
    );
};

export const updateLessonProgress = async (lessonId: string, progressPercent: number): Promise<ApiResponse<void>> => {
    await delay(300); // Shorter delay for optimistic UI updates

    const lesson = mockLessons.find(l => l.id === lessonId);
    if (!lesson) return createErrorResponse("Lesson not found");

    lesson.progressPercent = progressPercent;
    if (progressPercent >= 100) {
        lesson.status = 'completed';
    }

    return createSuccessResponse(undefined, "Progress updated");
};
