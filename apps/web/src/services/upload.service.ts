import { uploadApi } from '../mocks/api';

export const uploadService = {
    getHistory: () => uploadApi.getUploadHistory(),
    uploadContent: (file: File) => uploadApi.uploadFile(file),
    pollStatus: (uploadId: string) => uploadApi.getUploadStatus(uploadId),
};
