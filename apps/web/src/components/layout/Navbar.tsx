"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Menu, X } from "lucide-react";
import Link from "next/link";
import Image from "next/image";

const navLinks = [
    { label: "How It Works", href: "#how-it-works" },
    { label: "Features", href: "#features" },
    { label: "Pricing", href: "#pricing" },
    { label: "FAQ", href: "#faq" },
];

export default function Navbar() {
    const [isScrolled, setIsScrolled] = useState(false);
    const [isMobileOpen, setIsMobileOpen] = useState(false);

    useEffect(() => {
        const handleScroll = () => setIsScrolled(window.scrollY > 20);
        window.addEventListener("scroll", handleScroll, { passive: true });
        return () => window.removeEventListener("scroll", handleScroll);
    }, []);

    return (
        <motion.div
            initial={{ y: -24, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.5, ease: "easeOut" }}
            className="fixed top-0 inset-x-0 z-50 flex justify-center px-4 pt-3 lg:pt-4"
        >
            <div className="relative w-full max-w-5xl">
                <nav
                    className={`relative rounded-full border border-white/60 transition-all duration-500 ease-out ${isScrolled
                            ? "bg-white/70 backdrop-blur-2xl backdrop-saturate-150 shadow-[0_10px_40px_-8px_rgba(7,23,44,0.18),inset_0_1px_0_rgba(255,255,255,0.6)]"
                            : "bg-white/40 backdrop-blur-xl backdrop-saturate-150 shadow-[0_8px_30px_-10px_rgba(7,23,44,0.10),inset_0_1px_0_rgba(255,255,255,0.5)]"
                        }`}
                >
                    {/* Liquid sheen along the top edge */}
                    <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-gradient-to-r from-transparent via-white/90 to-transparent" />
                    {/* Soft ambient tint, gives the glass a hint of color instead of reading flat-grey */}
                    <div
                        className="pointer-events-none absolute inset-0 rounded-full opacity-60"
                        style={{
                            background:
                                "radial-gradient(120px 40px at 12% 0%, rgba(198,164,92,0.10), transparent 70%)",
                        }}
                    />

                    <div className="relative flex items-center justify-between h-14 px-3 lg:px-4">
                        {/* Logo */}
                        <Link href="/" className="flex items-center gap-2 pl-2">
                            <Image src="/logo.jpeg" alt="HIE Logo" width={30} height={30} className="rounded-lg object-contain" />
                            <span className="text-[0.95rem] font-serif font-semibold text-foreground tracking-tight">
                                HIEIQ<span className="text-primary">.AI</span>
                            </span>
                        </Link>

                        {/* Desktop Nav */}
                        <div className="hidden md:flex items-center gap-1 bg-black/[0.03] rounded-full p-1">
                            {navLinks.map((link) => (
                                <a
                                    key={link.label}
                                    href={link.href}
                                    className="px-3.5 py-1.5 rounded-full text-[0.82rem] font-medium text-text-secondary hover:text-foreground hover:bg-white/80 transition-all duration-200"
                                >
                                    {link.label}
                                </a>
                            ))}
                        </div>

                        {/* Desktop CTA */}
                        <div className="hidden md:flex items-center gap-3 pr-1">
                            <Link
                                href="/signin"
                                className="text-[0.82rem] font-medium text-text-secondary hover:text-foreground transition-colors"
                            >
                                Sign In
                            </Link>
                            <Link
                                href="/signup"
                                className="px-4 py-2 text-[0.82rem] font-semibold text-white bg-primary rounded-full hover:bg-primary-dark transition-colors shadow-[0_4px_14px_rgba(7,23,44,0.25)]"
                            >
                                Get Started
                            </Link>
                        </div>

                        {/* Mobile Menu Button */}
                        <button
                            onClick={() => setIsMobileOpen(!isMobileOpen)}
                            className="md:hidden p-2 mr-1"
                            aria-label="Toggle menu"
                        >
                            {isMobileOpen ? (
                                <X className="w-5 h-5 text-foreground" />
                            ) : (
                                <Menu className="w-5 h-5 text-foreground" />
                            )}
                        </button>
                    </div>
                </nav>

                {/* Mobile Menu — floating glass panel, matches the pill's width exactly */}
                <AnimatePresence>
                    {isMobileOpen && (
                        <motion.div
                            initial={{ opacity: 0, y: -10, scale: 0.98 }}
                            animate={{ opacity: 1, y: 0, scale: 1 }}
                            exit={{ opacity: 0, y: -10, scale: 0.98 }}
                            transition={{ duration: 0.2 }}
                            className="md:hidden absolute top-[calc(100%+0.6rem)] left-0 right-0 rounded-3xl bg-white/80 backdrop-blur-2xl border border-white/60 shadow-[0_20px_50px_-10px_rgba(7,23,44,0.2)] overflow-hidden"
                        >
                            <div className="px-4 py-4 space-y-1">
                                {navLinks.map((link) => (
                                    <a
                                        key={link.label}
                                        href={link.href}
                                        onClick={() => setIsMobileOpen(false)}
                                        className="block px-3 py-2.5 rounded-xl text-sm text-text-secondary hover:text-foreground hover:bg-black/[0.03] transition-colors"
                                    >
                                        {link.label}
                                    </a>
                                ))}
                                <div className="pt-3 mt-2 border-t border-[var(--color-border-soft)] space-y-2">
                                    <Link
                                        href="/signin"
                                        className="block px-3 py-2.5 rounded-xl text-sm text-text-secondary"
                                    >
                                        Sign In
                                    </Link>
                                    <Link
                                        href="/signup"
                                        className="block w-full text-center px-3 py-2.5 text-sm font-semibold text-white bg-primary rounded-xl"
                                    >
                                        Get Started
                                    </Link>
                                </div>
                            </div>
                        </motion.div>
                    )}
                </AnimatePresence>
            </div>
        </motion.div>
    );
}
