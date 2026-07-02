import { UploadFlow } from "@/components/dashboard/upload/UploadFlow";

export const metadata = {
    title: "Upload Material | HIE",
};

export default function UploadPage() {
    return (
        <div className="w-full max-w-[1000px] mx-auto pt-6 pb-20 flex flex-col min-h-[80vh]">
            <div className="mb-10">
                <h1 className="text-3xl font-bold tracking-tight text-neutral-900 mb-2">
                    Upload Material
                </h1>
                <p className="text-neutral-500 text-lg">
                    Drag and drop your PDF course material to instantly generate an interactive, audio-guided lesson.
                </p>
            </div>

            <div className="flex-1 flex flex-col items-center justify-center relative">
                {/* Decorative background glow for the active area */}
                <div className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 w-full max-w-[600px] aspect-square bg-gradient-to-br from-[var(--accent-primary)]/10 via-[var(--accent-secondary)]/10 to-transparent rounded-full blur-[100px] pointer-events-none" />

                <UploadFlow />
            </div>
        </div>
    );
}
