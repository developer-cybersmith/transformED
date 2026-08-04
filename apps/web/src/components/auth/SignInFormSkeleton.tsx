export function SignInFormSkeleton() {
    return (
        <div
            className="bg-white/80 backdrop-blur-xl rounded-[2rem] p-8 sm:p-10 shadow-[0_8px_40px_-12px_rgba(0,0,0,0.1)] border border-neutral-100 animate-pulse"
            aria-hidden="true"
        >
            <div className="mb-10 space-y-3">
                <div className="h-8 w-2/3 rounded-lg bg-neutral-200" />
                <div className="h-4 w-1/2 rounded bg-neutral-100" />
            </div>

            <div className="space-y-6">
                <div className="space-y-5">
                    <div className="space-y-2">
                        <div className="h-4 w-24 rounded bg-neutral-100" />
                        <div className="h-12 w-full rounded-xl bg-neutral-100" />
                    </div>
                    <div className="space-y-2">
                        <div className="h-4 w-20 rounded bg-neutral-100" />
                        <div className="h-12 w-full rounded-xl bg-neutral-100" />
                    </div>
                </div>

                <div className="h-4 w-32 rounded bg-neutral-100" />

                <div className="h-12 w-full rounded-xl bg-neutral-200" />
            </div>

            <div className="mt-8 mb-8 h-px w-full bg-neutral-100" />

            <div className="h-12 w-full rounded-xl bg-neutral-100" />

            <div className="mt-8 flex justify-center">
                <div className="h-4 w-40 rounded bg-neutral-100" />
            </div>
        </div>
    );
}
