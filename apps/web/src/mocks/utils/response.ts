export interface ApiResponse<T> {
    success: boolean;
    data: T | null;
    message: string;
}

export function createSuccessResponse<T>(data: T, message: string = "Success"): ApiResponse<T> {
    return {
        success: true,
        data,
        message,
    };
}

export function createErrorResponse<T = null>(message: string = "An error occurred"): ApiResponse<T> {
    return {
        success: false,
        data: null,
        message,
    };
}
