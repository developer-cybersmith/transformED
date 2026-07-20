import { useState } from "react";
import { KeyRound, LogOut, Trash2, Wallet } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { ChangePasswordModal } from "@/components/settings/ChangePasswordModal";

export function AccountTab() {
    const { logout } = useAuth();
    const [isChangePasswordOpen, setIsChangePasswordOpen] = useState(false);

    return (
        <div className="flex flex-col gap-10 w-full max-w-3xl pt-8 pb-12">
            <div>
                <h2 className="font-serif text-2xl font-semibold text-neutral-900 tracking-tight mb-2">Account & Billing</h2>
                <p className="text-neutral-500">Manage your subscription, security, and account lifecycle.</p>
            </div>

            <div className="flex flex-col gap-8">

                {/* Current Plan block */}
                <div className="flex items-center justify-between p-6 rounded-2xl bg-white border border-neutral-100 shadow-sm">
                    <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-[var(--color-light-bg)] text-[var(--accent-primary)] flex items-center justify-center">
                            <Wallet className="w-6 h-6" />
                        </div>
                        <div className="flex flex-col">
                            <span className="text-sm text-neutral-500 font-medium">Current Plan</span>
                            <span className="text-xl font-semibold text-neutral-900">Free Plan</span>
                        </div>
                    </div>
                    <Button
                        variant="primary"
                        size="sm"
                        className="rounded-lg bg-neutral-900 text-white hover:bg-neutral-800 shadow-sm"
                    >
                        Upgrade to Premium
                    </Button>
                </div>

                {/* Account Actions */}
                <div className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold text-neutral-900 uppercase tracking-wider mb-2 pl-1">Actions</h3>

                    <Button
                        variant="outline"
                        onClick={() => setIsChangePasswordOpen(true)}
                        className="h-auto w-full justify-start gap-3 rounded-xl border-neutral-100 bg-white p-4 text-left font-medium text-neutral-800 hover:bg-neutral-50 hover:border-neutral-200 group"
                    >
                        <KeyRound className="w-5 h-5 text-neutral-500 group-hover:text-neutral-700 transition-colors" />
                        Change Password
                    </Button>

                    <Button
                        variant="outline"
                        onClick={logout}
                        className="h-auto w-full justify-start gap-3 rounded-xl border-neutral-100 bg-white p-4 text-left font-medium text-neutral-800 hover:bg-neutral-50 hover:border-neutral-200 group"
                    >
                        <LogOut className="w-5 h-5 text-neutral-500 group-hover:text-neutral-700 transition-colors" />
                        Sign Out
                    </Button>

                    <div className="pt-6 mt-4 border-t border-neutral-100">
                        <Button
                            variant="ghost"
                            className="h-auto w-full justify-start gap-3 rounded-xl border border-transparent p-4 text-left font-medium text-neutral-500 hover:border-red-100 hover:bg-red-50/50 hover:text-red-600 group"
                        >
                            <Trash2 className="w-5 h-5 opacity-70 group-hover:opacity-100" />
                            Delete Account
                        </Button>
                        <p className="px-4 mt-2 text-xs text-neutral-400">
                            Deleting your account is permanent. All associated learning data will be removed.
                        </p>
                    </div>
                </div>

            </div>

            <ChangePasswordModal isOpen={isChangePasswordOpen} onClose={() => setIsChangePasswordOpen(false)} />
        </div>
    );
}
