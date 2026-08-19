"use client";

import Link from "next/link";
import Image from "next/image";
import { Clock } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

export default function PendingApprovalPage() {
    const { logout } = useAuth();

    return (
        <div className="flex min-h-screen w-full items-center justify-center bg-white p-8 overflow-hidden selection:bg-[var(--accent-primary)]/20 selection:text-[var(--accent-primary)]">
            <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] bg-[var(--accent-primary)]/10 blur-[120px] rounded-full pointer-events-none" />
            <div className="absolute bottom-[-10%] right-[-10%] w-[40%] h-[40%] bg-[var(--accent-secondary)]/10 blur-[100px] rounded-full pointer-events-none" />

            <div className="w-full max-w-[440px] relative z-10 text-center">
                <Link href="/" className="flex items-center justify-center gap-2 mb-10">
                    <Image src="/logo.jpeg" alt="HIE Logo" width={32} height={32} className="rounded-lg object-contain" />
                    <span className="text-2xl font-serif font-semibold text-[var(--accent-primary)]">
                        HIEIQ<span className="text-[var(--accent-primary)]">.AI</span>
                    </span>
                </Link>

                <div className="bg-white/60 backdrop-blur-xl border border-white/40 shadow-[0_8px_30px_rgb(0,0,0,0.04)] rounded-3xl p-10">
                    <div className="w-12 h-12 rounded-full bg-[var(--accent-primary)]/10 flex items-center justify-center text-[var(--accent-primary)] mx-auto mb-6">
                        <Clock className="w-6 h-6" />
                    </div>

                    <h1 className="font-serif text-2xl font-semibold text-neutral-900 mb-3">
                        You&apos;re on the list
                    </h1>
                    <p className="text-neutral-600 leading-relaxed mb-8">
                        HIE is in a limited access period right now. We&apos;ll email you as soon as your
                        account is activated — no need to do anything else in the meantime.
                    </p>

                    <button
                        type="button"
                        onClick={() => logout()}
                        className="w-full px-4 py-2.5 text-sm font-medium text-neutral-600 hover:text-neutral-900 border border-neutral-200 hover:bg-neutral-50 rounded-xl transition-colors"
                    >
                        Sign out
                    </button>
                </div>
            </div>
        </div>
    );
}
