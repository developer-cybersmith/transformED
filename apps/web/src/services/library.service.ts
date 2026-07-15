import { lessonsService } from "./lessons.service";
import { createSuccessResponse, createErrorResponse, ApiResponse } from "../mocks/utils/response";
import type { LessonStatusResponse } from "./upload.service";

export interface LibraryData {
    lessons: LessonStatusResponse[];
}

export const LIBRARY_PAGE_SIZE = 24;

export const libraryService = {
    getLibrary: async (): Promise<ApiResponse<LibraryData>> => {
        try {
            const lessons = await lessonsService.listLessons({ limit: LIBRARY_PAGE_SIZE, offset: 0 });
            return createSuccessResponse({ lessons }, "Library retrieved successfully");
        } catch (err) {
            console.error("Failed to fetch library data:", err);
            return createErrorResponse<LibraryData>("We couldn't load your library right now.");
        }
    },
};
