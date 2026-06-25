import { KeyRound, LogOut, Trash2, Wallet } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";

export function AccountTab() {
    const { logout } = useAuth();

    return (
        <div className="flex flex-col gap-10 w-full max-w-3xl pt-8 pb-12">
            <div>
                <h2 className="text-2xl font-semibold text-neutral-900 tracking-tight mb-2">Account & Billing</h2>
                <p className="text-neutral-500">Manage your subscription, security, and account lifecycle.</p>
            </div>

            <div className="flex flex-col gap-8">

                {/* Current Plan block */}
                <div className="flex items-center justify-between p-6 rounded-2xl bg-white border border-neutral-100 shadow-sm">
                    <div className="flex items-center gap-4">
                        <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
                            <Wallet className="w-6 h-6" />
                        </div>
                        <div className="flex flex-col">
                            <span className="text-sm text-neutral-500 font-medium">Current Plan</span>
                            <span className="text-xl font-semibold text-neutral-900">Free Plan</span>
                        </div>
                    </div>
                    <button className="px-5 py-2.5 rounded-lg bg-neutral-900 text-white font-medium text-sm hover:bg-neutral-800 transition-colors shadow-sm">
                        Upgrade to Premium
                    </button>
                </div>

                {/* Account Actions */}
                <div className="flex flex-col gap-2">
                    <h3 className="text-sm font-semibold text-neutral-900 uppercase tracking-wider mb-2 pl-1">Actions</h3>

                    <button className="flex items-center gap-3 w-full p-4 rounded-xl text-left bg-white border border-neutral-100 hover:bg-neutral-50 hover:border-neutral-200 transition-all text-neutral-800 group">
                        <KeyRound className="w-5 h-5 text-neutral-500 group-hover:text-neutral-700 transition-colors" />
                        <span className="font-medium">Change Password</span>
                    </button>

                    <button onClick={logout} className="flex items-center gap-3 w-full p-4 rounded-xl text-left bg-white border border-neutral-100 hover:bg-neutral-50 hover:border-neutral-200 transition-all text-neutral-800 group">
                        <LogOut className="w-5 h-5 text-neutral-500 group-hover:text-neutral-700 transition-colors" />
                        <span className="font-medium">Sign Out</span>
                    </button>

                    <div className="pt-6 mt-4 border-t border-neutral-100">
                        <button className="flex items-center gap-3 w-full p-4 rounded-xl text-left border border-transparent hover:border-red-100 hover:bg-red-50/50 transition-all text-neutral-500 hover:text-red-600 group">
                            <Trash2 className="w-5 h-5 opacity-70 group-hover:opacity-100" />
                            <span className="font-medium">Delete Account</span>
                        </button>
                        <p className="px-4 mt-2 text-xs text-neutral-400">
                            Deleting your account is permanent. All associated learning data will be removed.
                        </p>
                    </div>
                </div>

            </div>
        </div>
    );
}
