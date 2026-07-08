import Link from "next/link";
import Image from "next/image";
import { LearnerEvolution } from "@/components/auth/LearnerEvolution";
import { SignUpForm } from "@/components/auth/SignUpForm";

export default function SignUpPage() {
    return (
        <div className="flex h-screen w-full bg-white selection:bg-[var(--accent-primary)]/20 selection:text-[var(--accent-primary)] overflow-hidden">

            {/* Left Side: Storytelling (60%) */}
            <div className="hidden lg:flex w-[60%] flex-col relative bg-neutral-900 text-white">
                {/* Soft Background Gradients for Dark Mode */}
                <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-[var(--accent-primary)]/20 blur-[150px] rounded-full pointer-events-none" />
                <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-[var(--accent-secondary)]/20 blur-[130px] rounded-full pointer-events-none" />

                {/* Ambient Grid overlay */}
                <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-[0.03] pointer-events-none mix-blend-overlay"></div>

                <div className="flex-1 flex flex-col justify-center p-20 relative z-10 w-full max-w-2xl mx-auto">
                    <Link href="/" className="flex items-center gap-2 mb-12">
                        <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg object-contain" />
                        <span className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-white/70">
                            HIEIQ.AI
                        </span>
                    </Link>

                    <div className="border-l-4 border-[var(--accent-secondary)] pl-6 mb-8">
                        <h1 className="text-4xl md:text-5xl lg:text-5xl font-semibold tracking-tight mb-4 leading-[1.15]">
                            Stop Consuming.<br />
                            <span className="bg-clip-text text-transparent bg-gradient-to-r from-white to-[var(--accent-secondary)]">Start Becoming.</span>
                        </h1>
                        <p className="text-lg text-neutral-400 leading-relaxed max-w-md">
                            Build the capacity to think independently. Move away from shallow distraction toward deep, guided mastery.
                        </p>
                    </div>

                    {/* Learner Evolution Visualization Component */}
                    <div className="bg-white/5 backdrop-blur-xl border border-white/10 rounded-3xl p-8 shadow-2xl relative overflow-hidden">
                        <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-primary)]/10 blur-[50px] rounded-full pointer-events-none" />
                        <h3 className="text-sm font-semibold tracking-wider text-neutral-300 uppercase mb-6">The Journey</h3>
                        <LearnerEvolution />
                    </div>

                    <div className="mt-12 flex items-center gap-6 text-sm text-neutral-400">
                        <div className="flex items-center gap-2 bg-white/5 px-4 py-2 rounded-full border border-white/5">
                            <span className="flex items-center justify-center w-4 h-4 rounded-full bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] text-[10px]">✓</span>
                            Free pathway
                        </div>
                        <div className="flex items-center gap-2 bg-white/5 px-4 py-2 rounded-full border border-white/5">
                            <span className="flex items-center justify-center w-4 h-4 rounded-full bg-[var(--accent-primary)]/20 text-[var(--accent-primary)] text-[10px]">✓</span>
                            No credit card
                        </div>
                    </div>
                </div>
            </div>

            {/* Right Side: Floating Form (40%) */}
            <div className="w-full lg:w-[40%] flex items-center justify-center p-8 sm:p-12 relative bg-neutral-50 lg:bg-white overflow-y-auto overflow-x-hidden">
                <div className="absolute inset-0 bg-[url('https://grainy-gradients.vercel.app/noise.svg')] opacity-[0.02] pointer-events-none mix-blend-overlay lg:hidden"></div>
                {/* Soft Background Gradients for Mobile */}
                <div className="absolute top-0 right-0 w-full h-[50vh] bg-gradient-to-b from-neutral-900 to-transparent lg:hidden pointer-events-none" />

                <div className="w-full max-w-[420px] relative z-10">
                    <div className="lg:hidden mb-10 text-center">
                        <Link href="/" className="flex items-center justify-center gap-2">
                            <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg object-contain" />
                            <span className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-white to-white/80 lg:from-[var(--accent-primary)] lg:to-[var(--accent-primary-hover)] drop-shadow-md lg:drop-shadow-none">
                                HIEIQ.AI
                            </span>
                        </Link>
                    </div>

                    <SignUpForm />

                </div>
            </div>

        </div>
    );
}
