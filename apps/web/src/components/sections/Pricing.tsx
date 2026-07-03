"use client";

import { useState, useRef } from "react";
import { motion } from "framer-motion";
import { Check } from "lucide-react";
import Link from "next/link";
import confetti from "canvas-confetti";
import NumberFlow from "@number-flow/react";
import { useMediaQuery } from "@/hooks/use-media-query";
import { cn } from "@/lib/utils";

const plans = [
    {
        name: "Free",
        price: 0,
        yearlyPrice: 0,
        period: "",
        description: "Explore HIE with 3 PDFs a month.",
        features: [
            "3 PDF uploads / month",
            "AI tutoring (basic)",
            "Lesson generation",
            "Progress tracking",
        ],
        cta: "Get started",
        href: "/signup",
        highlighted: false,
    },
    {
        name: "Pro",
        price: 12,
        yearlyPrice: 9,
        period: "mo",
        description: "Unlimited learning for students who are serious about results.",
        features: [
            "Unlimited PDFs",
            "Advanced AI tutoring",
            "Teach-back exercises",
            "Priority generation",
            "Detailed mastery analytics",
            "Priority support",
        ],
        cta: "Start 7-day free trial",
        href: "/signup",
        highlighted: true,
    },
    {
        name: "Teams",
        price: 8,
        yearlyPrice: 6,
        period: "seat/mo",
        description: "For study groups, classrooms, or departments.",
        features: [
            "Everything in Pro",
            "Team management",
            "Shared lesson libraries",
            "Analytics dashboard",
            "Dedicated onboarding",
        ],
        cta: "Talk to us",
        href: "#",
        highlighted: false,
    },
];

export default function Pricing() {
    const [isMonthly, setIsMonthly] = useState(true);
    const isDesktop = useMediaQuery("(min-width: 768px)");
    const switchRef = useRef<HTMLButtonElement>(null);

    const handleToggle = () => {
        const nextVal = !isMonthly;
        setIsMonthly(nextVal);

        // Only fire confetti when toggling to Annual (isMonthly becomes false in the next state)
        if (!nextVal && switchRef.current) {
            const rect = switchRef.current.getBoundingClientRect();
            const x = rect.left + rect.width / 2;
            const y = rect.top + rect.height / 2;

            confetti({
                particleCount: 50,
                spread: 60,
                origin: {
                    x: x / window.innerWidth,
                    y: y / window.innerHeight,
                },
                colors: [
                    "#07172C", // primary (navy)
                    "#C6A45C", // accent (gold)
                    "#040D19", // dark (navy-dark)
                    "#EDEFF3", // soft wrapper (light navy-tint)
                ],
                ticks: 200,
                gravity: 1.2,
                decay: 0.94,
                startVelocity: 30,
                shapes: ["circle"],
            });
        }
    };

    return (
        <section id="pricing" className="py-20 lg:py-28 bg-white overflow-hidden">
            <div className="max-w-5xl mx-auto px-6 lg:px-8">
                {/* Header */}
                <motion.div
                    initial={{ opacity: 0, y: 16 }}
                    whileInView={{ opacity: 1, y: 0 }}
                    viewport={{ once: true, margin: "-80px" }}
                    transition={{ duration: 0.4 }}
                    className="text-center max-w-xl mx-auto mb-10"
                >
                    <h2 className="text-3xl sm:text-[2.25rem] font-serif text-foreground tracking-tight leading-tight mb-3">
                        <span className="font-semibold">Simple</span> <span className="italic font-normal text-text-secondary">pricing</span>
                    </h2>
                    <p className="text-text-secondary text-[1.05rem]">
                        Start free. Upgrade when you need more.
                    </p>
                </motion.div>

                {/* Toggle Switch */}
                <div className="flex justify-center items-center mb-14 gap-3 relative z-20">
                    <span className={cn("text-sm font-medium transition-colors", isMonthly ? "text-foreground" : "text-text-muted")}>
                        Monthly
                    </span>
                    <button
                        ref={switchRef}
                        onClick={handleToggle}
                        className={cn(
                            "relative inline-flex h-6 w-11 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 focus-visible:ring-offset-background",
                            isMonthly ? "bg-[#cbd5e1]" : "bg-primary"
                        )}
                        role="switch"
                        aria-checked={!isMonthly}
                    >
                        <span
                            className={cn(
                                "pointer-events-none block h-5 w-5 rounded-full bg-white shadow-lg ring-0 transition-transform",
                                isMonthly ? "translate-x-0" : "translate-x-5"
                            )}
                        />
                    </button>
                    <span className={cn("text-sm font-semibold transition-colors flex items-center gap-1.5", !isMonthly ? "text-foreground" : "text-text-muted")}>
                        Annually
                        <span className="text-[10px] uppercase font-bold tracking-wider text-primary bg-primary/10 px-2 py-0.5 rounded-full">Save 20%</span>
                    </span>
                </div>

                {/* Cards */}
                <div className="grid md:grid-cols-3 gap-5 mt-8">
                    {plans.map((plan, index) => (
                        <motion.div
                            key={plan.name}
                            initial={{ y: 30, opacity: 0 }}
                            whileInView={{ y: 0, opacity: 1 }}
                            viewport={{ once: true, margin: "-40px" }}
                            whileHover={{ y: -4 }}
                            transition={{
                                duration: 0.8,
                                delay: index * 0.1,
                                ease: "easeOut"
                            }}
                            className={cn(
                                `rounded-2xl p-6 lg:p-8 flex flex-col transition-all`,
                                plan.highlighted
                                    ? "bg-foreground text-white ring-1 ring-foreground shadow-2xl hover:shadow-[0_20px_40px_rgba(0,0,0,0.4)]"
                                    : "bg-[#f8fafc] border border-[#e8eef3] shadow-lg hover:shadow-[0_20px_40px_rgba(0,0,0,0.08)]",
                            )}
                        >
                            <p className={cn("text-sm font-semibold mb-3", plan.highlighted ? "text-white/70" : "text-text-muted")}>
                                {plan.name}
                            </p>

                            <div className="flex items-baseline gap-1 mb-1 relative min-h-[50px]">
                                {plan.price === 0 ? (
                                    <span className={cn("text-4xl font-serif font-semibold tracking-tight", plan.highlighted ? "text-white" : "text-foreground")}>
                                        Free
                                    </span>
                                ) : (
                                    <NumberFlow
                                        value={isMonthly ? plan.price : plan.yearlyPrice}
                                        format={{
                                            style: "currency",
                                            currency: "USD",
                                            minimumFractionDigits: 0,
                                            maximumFractionDigits: 0,
                                        }}
                                        transformTiming={{
                                            duration: 500,
                                            easing: "ease-out",
                                        }}
                                        willChange
                                        className={cn("text-4xl font-serif font-semibold tabular-nums tracking-tight", plan.highlighted ? "text-white" : "text-foreground")}
                                    />
                                )}
                                {plan.period && plan.price !== 0 && (
                                    <span className={cn("text-sm", plan.highlighted ? "text-white/50" : "text-text-muted")}>
                                        /{plan.period}
                                    </span>
                                )}
                            </div>
                            <p className={cn("text-sm mb-6 leading-relaxed", plan.highlighted ? "text-white/60" : "text-text-secondary")}>
                                {plan.description}
                            </p>

                            <ul className="space-y-3 mb-8 flex-1">
                                {plan.features.map((f) => (
                                    <li key={f} className="flex items-start gap-2.5 text-[0.9rem]">
                                        <Check className={cn("w-4 h-4 shrink-0 mt-0.5", plan.highlighted ? "text-emerald-400" : "text-emerald-500")} />
                                        <span className={plan.highlighted ? "text-white/80" : "text-text-secondary"}>{f}</span>
                                    </li>
                                ))}
                            </ul>

                            <Link href={plan.href} className="mt-auto block w-full">
                                <motion.div
                                    whileHover={{ y: -2 }}
                                    whileTap={{ y: 1 }}
                                    transition={{ type: "spring", stiffness: 400, damping: 25 }}
                                    className={cn(
                                        "w-full text-center py-3 rounded-xl text-sm font-semibold transition-colors shadow-sm",
                                        plan.highlighted
                                            ? "bg-white text-foreground shadow-[0_4px_14px_rgba(255,255,255,0.25)]"
                                            : "bg-white border border-[#e2e8f0] text-foreground shadow-[0_2px_8px_rgba(0,0,0,0.04)]"
                                    )}
                                >
                                    {plan.cta}
                                </motion.div>
                            </Link>
                        </motion.div>
                    ))}
                </div>
            </div>
        </section>
    );
}
