import { MapPin, Target, Sparkles, BookOpen } from "lucide-react";

export function ProfileTab() {
    return (
        <div className="flex flex-col gap-8 w-full max-w-3xl pt-8">
            <h2 className="text-2xl font-semibold text-neutral-900 tracking-tight">Profile & Identity</h2>

            <div className="flex flex-col md:flex-row gap-8 items-start">
                {/* Profile Avatar / Photo */}
                <div className="relative flex-shrink-0 group">
                    <div className="w-32 h-32 rounded-2xl bg-gradient-to-tr from-blue-100 to-indigo-50 p-1 flex items-center justify-center shadow-sm">
                        <div className="w-full h-full rounded-xl bg-white flex items-center justify-center overflow-hidden relative">
                            {/* Dummy Image Placeholder */}
                            <img
                                src="https://api.dicebear.com/7.x/notionists/svg?seed=Alex&backgroundColor=f8fafc"
                                alt="Profile Avatar"
                                className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
                            />
                        </div>
                    </div>
                </div>

                {/* Profile Details */}
                <div className="flex flex-col gap-6 flex-1">
                    <div>
                        <h3 className="text-xl font-medium text-neutral-900">Alex Student</h3>
                        <p className="text-neutral-500 mt-1">alex.student@example.com</p>
                    </div>

                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                        <div className="flex flex-col gap-1.5 p-4 rounded-xl bg-white border border-neutral-100 shadow-sm">
                            <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider flex items-center gap-1.5">
                                <Target className="w-3.5 h-3.5" /> Learning Goal
                            </span>
                            <span className="text-neutral-900 font-medium">Master Advanced Calculus</span>
                        </div>
                        <div className="flex flex-col gap-1.5 p-4 rounded-xl bg-white border border-neutral-100 shadow-sm">
                            <span className="text-xs font-medium text-neutral-500 uppercase tracking-wider flex items-center gap-1.5">
                                <BookOpen className="w-3.5 h-3.5" /> Academic Focus
                            </span>
                            <span className="text-neutral-900 font-medium">Mathematics & Physics</span>
                        </div>
                    </div>

                    {/* Learning Stage Badge */}
                    <div className="mt-2 p-5 rounded-xl bg-gradient-to-r from-blue-50 to-indigo-50/50 border border-blue-100 flex items-center justify-between">
                        <div className="flex flex-col gap-1">
                            <span className="text-sm text-blue-600 font-medium flex items-center gap-1.5">
                                <Sparkles className="w-4 h-4" /> Current Stage
                            </span>
                            <span className="text-lg font-semibold text-blue-900">Guided Learner</span>
                        </div>
                        <div className="text-right">
                            <button suppressHydrationWarning className="text-sm font-medium text-blue-600 hover:text-blue-700 transition-colors">
                                View Journey Map
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
