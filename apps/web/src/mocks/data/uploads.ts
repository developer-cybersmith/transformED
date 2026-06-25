export type UploadStatus =
    | 'Uploaded'
    | 'Analyzing PDF'
    | 'Segmenting Chapters'
    | 'Generating Lessons'
    | 'Generating Audio'
    | 'Finalizing'
    | 'Ready'
    | 'Failed';

export interface MockUpload {
    id: string;
    fileName: string;
    sizeBytes: number;
    pages: number;
    uploadedAt: string;
    status: UploadStatus;
}

export const mockUploads: MockUpload[] = [
    {
        id: "upl_1",
        fileName: "Advanced Web Security.pdf",
        sizeBytes: 4500123,
        pages: 142,
        uploadedAt: "2026-06-18T08:30:00Z",
        status: "Ready"
    },
    {
        id: "upl_2",
        fileName: "Machine Learning Fundamentals.pdf",
        sizeBytes: 8200500,
        pages: 350,
        uploadedAt: "2026-06-18T10:15:00Z",
        status: "Generating Lessons"
    },
    {
        id: "upl_3",
        fileName: "Introduction to Operating Systems.pdf",
        sizeBytes: 2100400,
        pages: 89,
        uploadedAt: "2026-06-17T14:20:00Z",
        status: "Failed"
    }
];
