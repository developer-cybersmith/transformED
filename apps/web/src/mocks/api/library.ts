import { randomDelay } from '../utils/delay';
import { createSuccessResponse, ApiResponse } from '../utils/response';
import { mockLessons, MockLesson } from '../data/lessons';

export interface LibraryData {
    inProgress: MockLesson[];
    completed: MockLesson[];
    processing: MockLesson[];
    failed: MockLesson[];
}

export const getLibrary = async (): Promise<ApiResponse<LibraryData>> => {
    // Library can be slightly slower
    await randomDelay(500, 1000);

    const data: LibraryData = {
        inProgress: mockLessons.filter(l => l.status === 'in_progress'),
        completed: mockLessons.filter(l => l.status === 'completed'),
        processing: mockLessons.filter(l => l.status === 'processing'),
        failed: mockLessons.filter(l => l.status === 'failed')
    };

    return createSuccessResponse(data, "Library retrieved successfully");
};
