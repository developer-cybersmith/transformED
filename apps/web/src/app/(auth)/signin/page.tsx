import Link from "next/link";
import Image from "next/image";
import { SignInForm } from "@/components/auth/SignInForm";
import { BarChart3, Brain, Target, Sparkles } from "lucide-react";

export default function SignInPage() {
    return (
        <div className="flex h-screen w-full bg-white selection:bg-[var(--accent-primary)]/20 selection:text-[var(--accent-primary)] overflow-hidden">

            {/* Left Side: Experience Preivew (58%) */}
            <div className="hidden lg:flex w-[58%] flex-col relative bg-neutral-50/50">
                {/* Soft Background Gradients */}
                <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-[var(--accent-primary)]/10 blur-[120px] rounded-full pointer-events-none" />
                <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-[var(--accent-secondary)]/10 blur-[100px] rounded-full pointer-events-none" />

                <div className="flex-1 flex flex-col justify-center p-20 relative z-10">
                    <div className="max-w-xl">
                        <Link href="/" className="flex items-center gap-2 mb-16">
                            <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg object-contain" />
                            <span className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[var(--accent-primary)] to-[var(--accent-primary-hover)]">
                                HIEIQ<span className="text-[var(--accent-primary)]">.AI</span>
                            </span>
                        </Link>

                        <h1 className="text-4xl md:text-5xl font-semibold tracking-tight text-neutral-900 mb-6">
                            Continue Your Journey
                        </h1>
                        <p className="text-xl text-neutral-600 mb-16 leading-relaxed">
                            Continue building the capacity to think independently and explore without limits.
                        </p>

                        {/* Learning Environment Snapshot */}
                        <div className="bg-white/60 backdrop-blur-xl border border-white/40 shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-3xl p-8 relative overflow-hidden">
                            <div className="absolute top-0 right-0 w-32 h-32 bg-[var(--accent-primary)]/5 blur-[50px] rounded-full" />

                            <div className="flex items-center justify-between mb-8">
                                <div className="flex items-center gap-3">
                                    <div className="w-10 h-10 rounded-full bg-[var(--accent-primary)]/10 flex items-center justify-center text-[var(--accent-primary)]">
                                        <Brain className="w-5 h-5" />
                                    </div>
                                    <div>
                                        <h3 className="text-sm font-semibold text-neutral-900">AI Tutor Active</h3>
                                        <p className="text-xs text-neutral-500">Focus Environment: High</p>
                                    </div>
                                </div>
                                <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-600 text-xs font-medium border border-emerald-100">
                                    <span className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                                    Optimal State
                                </div>
                            </div>

                            <div className="pl-13 border-l-2 border-neutral-100 ml-5 py-2">
                                <div className="bg-white rounded-2xl p-5 shadow-sm border border-neutral-100 text-neutral-800 font-medium italic">
                                    "Before moving forward, explain the core idea in your own words."
                                </div>
                            </div>

                            <div className="mt-8 grid grid-cols-3 gap-4">
                                <div className="p-4 rounded-2xl bg-white/50 border border-white">
                                    <div className="flex items-center gap-2 text-neutral-500 text-xs mb-1">
                                        <Target className="w-3.5 h-3.5" />
                                        Concepts Mastered
                                    </div>
                                    <div className="text-2xl font-semibold text-neutral-900">42</div>
                                </div>
                                <div className="p-4 rounded-2xl bg-white/50 border border-white">
                                    <div className="flex items-center gap-2 text-neutral-500 text-xs mb-1">
                                        <Sparkles className="w-3.5 h-3.5" />
                                        Learning Streak
                                    </div>
                                    <div className="text-2xl font-semibold text-neutral-900">12<span className="text-sm font-normal text-neutral-500 ml-1">days</span></div>
                                </div>
                                <div className="p-4 rounded-2xl bg-white/50 border border-white">
                                    <div className="flex items-center gap-2 text-neutral-500 text-xs mb-1">
                                        <BarChart3 className="w-3.5 h-3.5" />
                                        Focus Time
                                    </div>
                                    <div className="text-2xl font-semibold text-neutral-900">5.2<span className="text-sm font-normal text-neutral-500 ml-1">hrs</span></div>
                                </div>
                            </div>
                        </div>

                    </div>
                </div>
            </div>

            {/* Right Side: Floating Form (42%) */}
            <div className="w-full lg:w-[42%] flex items-center justify-start lg:pl-16 p-8 sm:p-12 relative overflow-y-auto overflow-x-hidden">
                <div className="absolute inset-0 bg-white" />

                {/* Decorative elements for mobile only */}
                <div className="absolute top-0 right-0 w-full h-64 bg-gradient-to-b from-[var(--accent-primary)]/5 to-transparent lg:hidden pointer-events-none" />

                <div className="w-full max-w-[420px] relative z-10">
                    <div className="lg:hidden mb-10">
                        <Link href="/" className="flex items-center justify-center gap-2">
                            <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg object-contain" />
                            <span className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-[var(--accent-primary)] to-[var(--accent-primary-hover)]">
                                HIEIQ<span className="text-[var(--accent-primary)]">.AI</span>
                            </span>
                        </Link>
                    </div>

                    <SignInForm />

                </div>
            </div>

        </div>
    );
}
