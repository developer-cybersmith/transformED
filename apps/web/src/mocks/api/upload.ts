import { randomDelay, delay } from '../utils/delay';
import { createSuccessResponse, createErrorResponse, ApiResponse } from '../utils/response';
import { mockUploads, MockUpload, UploadStatus } from '../data/uploads';

export const getUploadHistory = async (): Promise<ApiResponse<MockUpload[]>> => {
    // Simulate 1000ms - 3000ms latency for fetching file trees
    await randomDelay(1000, 3000);
    return createSuccessResponse(mockUploads, "Upload history retrieved successfully");
};

export const uploadFile = async (file: File): Promise<ApiResponse<MockUpload>> => {
    // Simulate heavy upload latency
    await randomDelay(2000, 4000);

    const newUpload: MockUpload = {
        id: `upl_${Date.now()}`,
        fileName: file.name,
        sizeBytes: file.size,
        pages: Math.floor(Math.random() * 50) + 5, // Fake page count
        uploadedAt: new Date().toISOString(),
        status: 'Uploaded'
    };

    mockUploads.unshift(newUpload);
    return createSuccessResponse(newUpload, "File uploaded successfully");
};

export const getUploadStatus = async (uploadId: string): Promise<ApiResponse<{ status: UploadStatus }>> => {
    // Simulating rapid polling for websocket-like behavior
    await delay(200);
    const upload = mockUploads.find(u => u.id === uploadId);

    if (!upload) {
        return createErrorResponse("Upload not found");
    }

    return createSuccessResponse({ status: upload.status }, "Status retrieved");
};
