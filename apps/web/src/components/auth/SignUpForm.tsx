"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { motion } from "framer-motion";
import { Mail, Lock, User, ArrowRight } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { createClient } from "@/lib/supabase/client";

export function SignUpForm() {
    const router = useRouter();
    const supabase = createClient();
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState("");
    const [isSuccess, setIsSuccess] = useState(false);
    const [submittedEmail, setSubmittedEmail] = useState("");

    const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
        e.preventDefault();
        setIsLoading(true);
        setError("");

        // Read form values
        const formData = new FormData(e.currentTarget);
        const fullName = formData.get("fullName") as string;
        const email = formData.get("email") as string;
        const password = formData.get("password") as string;
        const confirmPassword = formData.get("confirmPassword") as string;

        if (password !== confirmPassword) {
            setError("Passwords do not match");
            setIsLoading(false);
            return;
        }

        if (password.length < 8) {
            setError("Password must be at least 8 characters");
            setIsLoading(false);
            return;
        }

        try {
            const { data, error: signUpError } = await supabase.auth.signUp({
                email,
                password,
                options: {
                    data: {
                        full_name: fullName
                    }
                }
            });

            if (signUpError) throw signUpError;

            if (data?.user && !data.session) {
                setSubmittedEmail(email);
                setIsSuccess(true);
                return;
            }

            // On success, redirect to dashboard.
            router.push("/dashboard");
        } catch (err: any) {
            console.error("Registration error:", err);
            setError(
                err.message ||
                "Registration failed. Please try again."
            );
        } finally {
            setIsLoading(false);
        }
    };

    const handleGoogleSignUp = () => {
        supabase.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo: `${window.location.origin}/auth/callback?next=/dashboard`
            }
        });
    };

    if (isSuccess) {
        return (
            <motion.div
                initial={{ opacity: 0, y: 20 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
                className="bg-white/80 backdrop-blur-xl rounded-[2rem] p-6 sm:p-8 shadow-[0_8px_40px_-12px_rgba(0,0,0,0.1)] border border-neutral-100 text-center"
            >
                <div className="mx-auto w-16 h-16 bg-[var(--accent-primary)]/10 rounded-full flex items-center justify-center mb-6">
                    <Mail className="w-8 h-8 text-[var(--accent-primary)]" />
                </div>
                <h2 className="font-serif text-2xl font-semibold tracking-tight text-neutral-900 mb-3">
                    Check your email
                </h2>
                <p className="text-neutral-600 text-sm sm:text-base leading-relaxed mb-8">
                    We've sent a confirmation link to <br /><span className="font-medium text-neutral-900 mt-1 inline-block">{submittedEmail}</span>.
                    <br /><br />Please click the link to activate your account.
                </p>
                <Link href="/signin">
                    <Button className="w-full" size="lg">
                        Return to sign in
                    </Button>
                </Link>
            </motion.div>
        );
    }

    return (
        <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="bg-white/80 backdrop-blur-xl rounded-[2rem] p-6 sm:p-8 shadow-[0_8px_40px_-12px_rgba(0,0,0,0.1)] border border-neutral-100"
        >
            <div className="mb-4 text-center lg:text-left">
                <h2 className="font-serif text-2xl font-semibold tracking-tight text-neutral-900 mb-1">
                    Join HIE
                </h2>
                <p className="text-neutral-500 text-sm">
                    Begin your journey toward intellectual independence.
                </p>
            </div>

            <form onSubmit={handleSubmit} className="space-y-4">
                {error && (
                    <div className="p-3 text-sm text-red-600 bg-red-50 border border-red-100 rounded-xl">
                        {error}
                    </div>
                )}

                <div className="space-y-3">
                    <div className="space-y-1.5">
                        <Label htmlFor="fullName">Full Name</Label>
                        <Input
                            id="fullName"
                            name="fullName"
                            type="text"
                            placeholder="J. Robert Oppenheimer"
                            required
                            icon={<User className="w-5 h-5" />}
                        />
                    </div>

                    <div className="space-y-1.5">
                        <Label htmlFor="email">Email address</Label>
                        <Input
                            id="email"
                            name="email"
                            type="email"
                            placeholder="name@example.com"
                            required
                            icon={<Mail className="w-5 h-5" />}
                        />
                    </div>

                    <div className="space-y-1.5">
                        <Label htmlFor="password">Password</Label>
                        <Input
                            id="password"
                            name="password"
                            type="password"
                            placeholder="••••••••"
                            required
                            icon={<Lock className="w-5 h-5" />}
                        />
                    </div>

                    <div className="space-y-1.5">
                        <Label htmlFor="confirmPassword">Confirm Password</Label>
                        <Input
                            id="confirmPassword"
                            name="confirmPassword"
                            type="password"
                            placeholder="••••••••"
                            required
                            icon={<Lock className="w-5 h-5" />}
                        />
                    </div>
                </div>

                <Button type="submit" className="w-full group mt-4" isLoading={isLoading} size="lg">
                    Start Your Transformation
                    <ArrowRight className="w-4 h-4 ml-2 mt-[1px] group-hover:translate-x-1 transition-transform" />
                </Button>
            </form>

            <div className="mt-6 mb-6 relative">
                <div className="absolute inset-0 flex items-center">
                    <div className="w-full border-t border-neutral-200/60" />
                </div>
                <div className="relative flex justify-center text-sm">
                    <span className="px-4 bg-white/0 backdrop-blur-sm text-neutral-500 text-xs font-medium uppercase tracking-wider">
                        Or sign up with
                    </span>
                </div>
            </div>

            <Button
                type="button"
                variant="outline"
                className="w-full relative bg-white"
                onClick={handleGoogleSignUp}
                disabled={isLoading}
                size="md"
            >
                <svg className="w-5 h-5 mr-3" viewBox="0 0 24 24">
                    {/* Exact Google Icon path here */}
                    <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4" />
                    <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853" />
                    <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l2.85-2.22.81-.62z" fill="#FBBC05" />
                    <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335" />
                    <path d="M1 1h22v22H1z" fill="none" />
                </svg>
                Sign up with Google
            </Button>

            <p className="mt-4 text-center text-sm text-neutral-600">
                Already learning with HIE?{" "}
                <Link
                    href="/signin"
                    className="font-medium text-[var(--accent-primary)] hover:text-[var(--accent-primary-hover)] transition-colors"
                >
                    Continue learning &rarr;
                </Link>
            </p>
        </motion.div>
    );
}
