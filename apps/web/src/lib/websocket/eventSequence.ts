export interface PipelineStage {
    stepName: string;
    progressPercent: number;
    minDelayMs: number;
    maxDelayMs: number;
}

/**
 * Simulates a believable, non-linear upload pipeline timing sequence.
 * This ensures the frontend UI can react exactly like it's processing real PDFs and Audio.
 */
export const EVENT_SEQUENCE: PipelineStage[] = [
    { stepName: "Upload Started", progressPercent: 5, minDelayMs: 300, maxDelayMs: 500 },
    { stepName: "PDF Received", progressPercent: 10, minDelayMs: 800, maxDelayMs: 1200 },
    { stepName: "PDF Analysis Started", progressPercent: 15, minDelayMs: 1000, maxDelayMs: 2000 },
    { stepName: "PDF Analysis Complete", progressPercent: 25, minDelayMs: 1000, maxDelayMs: 1500 },
    { stepName: "Chapter Segmentation Started", progressPercent: 30, minDelayMs: 500, maxDelayMs: 1000 },
    { stepName: "Chapter Segmentation Complete", progressPercent: 40, minDelayMs: 500, maxDelayMs: 1000 },
    { stepName: "Lesson Generation Started", progressPercent: 45, minDelayMs: 1000, maxDelayMs: 2000 },
    { stepName: "Lesson Generation", progressPercent: 65, minDelayMs: 2000, maxDelayMs: 4000 },
    { stepName: "Lesson Generation Complete", progressPercent: 75, minDelayMs: 500, maxDelayMs: 1200 },
    { stepName: "Audio Generation Started", progressPercent: 80, minDelayMs: 800, maxDelayMs: 1500 },
    { stepName: "Audio Generation", progressPercent: 85, minDelayMs: 2000, maxDelayMs: 3000 },
    { stepName: "Audio Generation Complete", progressPercent: 90, minDelayMs: 600, maxDelayMs: 1000 },
    { stepName: "Packaging", progressPercent: 95, minDelayMs: 1000, maxDelayMs: 1500 },
    { stepName: "Complete", progressPercent: 100, minDelayMs: 500, maxDelayMs: 1000 }
];
