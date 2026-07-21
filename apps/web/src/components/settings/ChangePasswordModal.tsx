"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { KeyRound, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { createClient } from "@/lib/supabase/client";
import { useAuth } from "@/contexts/AuthContext";

interface ChangePasswordModalProps {
    isOpen: boolean;
    onClose: () => void;
}

export function ChangePasswordModal({ isOpen, onClose }: ChangePasswordModalProps) {
    const { user } = useAuth();
    const [isMounted, setIsMounted] = useState(false);
    const [currentPassword, setCurrentPassword] = useState("");
    const [newPassword, setNewPassword] = useState("");
    const [confirmPassword, setConfirmPassword] = useState("");
    const [error, setError] = useState<string | null>(null);
    const [isSubmitting, setIsSubmitting] = useState(false);
    const [success, setSuccess] = useState(false);
    const closeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Portal target isn't available during SSR — flip to true post-hydration.
    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setIsMounted(true);
    }, []);

    // Clears the post-success auto-close timer on unmount — otherwise a stale
    // timer from a session the user already manually closed could fire
    // handleClose() against a since-reopened modal (review fix).
    useEffect(() => {
        return () => {
            if (closeTimerRef.current) clearTimeout(closeTimerRef.current);
        };
    }, []);

    function reset() {
        setCurrentPassword("");
        setNewPassword("");
        setConfirmPassword("");
        setError(null);
        setIsSubmitting(false);
        setSuccess(false);
    }

    function handleClose() {
        if (closeTimerRef.current) {
            clearTimeout(closeTimerRef.current);
            closeTimerRef.current = null;
        }
        reset();
        onClose();
    }

    async function handleSubmit(e: React.FormEvent) {
        e.preventDefault();
        // Reentrancy guard — a fast double-submit (double click / double Enter)
        // before React commits isSubmitting could otherwise fire two concurrent
        // signInWithPassword + updateUser sequences (review fix).
        if (isSubmitting) return;
        setError(null);

        if (newPassword.length < 8) {
            setError("New password must be at least 8 characters.");
            return;
        }
        if (newPassword !== confirmPassword) {
            setError("New password and confirmation do not match.");
            return;
        }
        if (newPassword === currentPassword) {
            setError("New password must be different from your current password.");
            return;
        }

        if (!user?.email) {
            setError("Your session has expired. Please sign in again.");
            return;
        }

        setIsSubmitting(true);
        try {
            const supabase = createClient();

            // Supabase's updateUser() alone would accept a new password on the
            // strength of the existing session JWT, with no proof the caller
            // still knows the current one — anyone with an unlocked/hijacked
            // session could lock the real owner out. Re-authenticating first
            // forces a fresh credential check against Supabase's auth server
            // (never done locally) before the update is allowed to proceed.
            const { error: reauthError } = await supabase.auth.signInWithPassword({
                email: user.email,
                password: currentPassword,
            });
            if (reauthError) {
                // Distinguish actual wrong-password from network/rate-limit/server
                // failures — collapsing all of these into "incorrect password" is
                // misleading and gives the user the wrong next action (review fix).
                if (reauthError.status === 429) {
                    setError("Too many attempts — please wait a moment and try again.");
                } else if (reauthError.status && reauthError.status >= 500) {
                    setError("Something went wrong on our end. Please try again.");
                } else {
                    setError("Current password is incorrect.");
                }
                return;
            }

            const { error: updateError } = await supabase.auth.updateUser({ password: newPassword });
            if (updateError) {
                setError(updateError.message);
                return;
            }

            setSuccess(true);
            closeTimerRef.current = setTimeout(handleClose, 1500);
        } catch {
            setError("Something went wrong. Please try again.");
        } finally {
            setIsSubmitting(false);
        }
    }

    // Rendered inline, this would sit inside <main>'s "relative z-10" stacking
    // context (apps/web/src/app/(dashboard)/settings/layout.tsx) — a child can
    // never out-stack a sibling of its ancestor no matter its own z-index, so
    // the fixed overlay would paint *under* the sidebar (also z-50, but outside
    // that context) instead of over it. Portaling to document.body escapes
    // that context entirely so the overlay/blur genuinely covers the viewport.
    if (!isMounted) return null;

    return createPortal(
        <AnimatePresence>
            {isOpen && (
                <motion.div
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="fixed inset-0 z-[100] flex items-center justify-center p-6 bg-neutral-900/40 backdrop-blur-sm"
                    onClick={handleClose}
                >
                    <motion.div
                        initial={{ opacity: 0, y: 10, scale: 0.97 }}
                        animate={{ opacity: 1, y: 0, scale: 1 }}
                        exit={{ opacity: 0, y: 10, scale: 0.97 }}
                        transition={{ duration: 0.15 }}
                        onClick={(e) => e.stopPropagation()}
                        className="w-full max-w-md bg-white rounded-2xl border border-neutral-100 shadow-[0_20px_60px_rgb(0,0,0,0.15)] overflow-hidden"
                    >
                        <div className="flex items-start justify-between p-6 border-b border-neutral-100">
                            <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-xl bg-[var(--color-light-bg)] text-[var(--accent-primary)] flex items-center justify-center">
                                    <KeyRound className="w-5 h-5" />
                                </div>
                                <div>
                                    <h3 className="font-serif text-lg font-semibold text-neutral-900">Change Password</h3>
                                    <p className="text-sm text-neutral-500">Update the password for your account.</p>
                                </div>
                            </div>
                            <button
                                type="button"
                                onClick={handleClose}
                                className="text-neutral-400 hover:text-neutral-700 transition-colors"
                                aria-label="Close"
                            >
                                <X className="w-5 h-5" />
                            </button>
                        </div>

                        {success ? (
                            <div className="p-6 text-sm text-emerald-600 font-medium">
                                Password updated successfully.
                            </div>
                        ) : (
                            <form onSubmit={handleSubmit} className="flex flex-col gap-4 p-6">
                                <label className="flex flex-col gap-1.5 text-sm">
                                    <span className="font-medium text-neutral-700">Current Password</span>
                                    <input
                                        type="password"
                                        required
                                        autoComplete="current-password"
                                        value={currentPassword}
                                        onChange={(e) => setCurrentPassword(e.target.value)}
                                        className="rounded-xl border border-neutral-200 px-4 py-2.5 text-neutral-900 focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]/20 focus:border-[var(--accent-primary)]/50 transition-colors"
                                    />
                                </label>
                                <label className="flex flex-col gap-1.5 text-sm">
                                    <span className="font-medium text-neutral-700">New Password</span>
                                    <input
                                        type="password"
                                        required
                                        minLength={8}
                                        autoComplete="new-password"
                                        value={newPassword}
                                        onChange={(e) => setNewPassword(e.target.value)}
                                        className="rounded-xl border border-neutral-200 px-4 py-2.5 text-neutral-900 focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]/20 focus:border-[var(--accent-primary)]/50 transition-colors"
                                    />
                                </label>
                                <label className="flex flex-col gap-1.5 text-sm">
                                    <span className="font-medium text-neutral-700">Confirm New Password</span>
                                    <input
                                        type="password"
                                        required
                                        minLength={8}
                                        autoComplete="new-password"
                                        value={confirmPassword}
                                        onChange={(e) => setConfirmPassword(e.target.value)}
                                        className="rounded-xl border border-neutral-200 px-4 py-2.5 text-neutral-900 focus:outline-none focus:ring-2 focus:ring-[var(--accent-primary)]/20 focus:border-[var(--accent-primary)]/50 transition-colors"
                                    />
                                </label>

                                {error && (
                                    <p className="text-sm text-red-600">{error}</p>
                                )}

                                <div className="flex justify-end gap-3 pt-2">
                                    <Button type="button" variant="ghost" onClick={handleClose}>
                                        Cancel
                                    </Button>
                                    <Button type="submit" variant="primary" isLoading={isSubmitting}>
                                        Update Password
                                    </Button>
                                </div>
                            </form>
                        )}
                    </motion.div>
                </motion.div>
            )}
        </AnimatePresence>,
        document.body
    );
}
