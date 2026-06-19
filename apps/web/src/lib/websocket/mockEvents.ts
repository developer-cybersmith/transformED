import { StatusEvent, ProgressEvent, CompletedEvent, ErrorEvent } from './types';

export const createStatusEvent = (status: string): StatusEvent => ({
    type: 'status',
    status
});

export const createProgressEvent = (progress: number, currentStep: string): ProgressEvent => ({
    type: 'progress',
    progress,
    currentStep
});

export const createCompletedEvent = (lessonId: string): CompletedEvent => ({
    type: 'completed',
    lessonId
});

export const createErrorEvent = (message: string): ErrorEvent => ({
    type: 'error',
    message
});
