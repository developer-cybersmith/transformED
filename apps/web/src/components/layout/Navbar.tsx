"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Menu, X } from "lucide-react";
import Link from "next/link";

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
        <motion.header
            initial={{ y: -10, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 0.4 }}
            className={`fixed top-0 left-0 right-0 z-50 transition-all duration-200 ${isScrolled
                    ? "bg-white/90 backdrop-blur-xl border-b border-[#f0f0f0]"
                    : "bg-transparent"
                }`}
        >
            <nav className="max-w-6xl mx-auto px-6 lg:px-8">
                <div className="flex items-center justify-between h-16">
                    {/* Logo */}
                    <Link href="/" className="flex items-center gap-2">
                        <div className="w-7 h-7 rounded-lg bg-primary flex items-center justify-center">
                            <span className="text-white font-bold text-xs font-display">T</span>
                        </div>
                        <span className="text-[0.95rem] font-semibold text-foreground tracking-tight font-display">
                            Transform<span className="text-primary">ED</span>
                        </span>
                    </Link>

                    {/* Desktop Nav */}
                    <div className="hidden md:flex items-center gap-1">
                        {navLinks.map((link) => (
                            <a
                                key={link.label}
                                href={link.href}
                                className="px-3.5 py-2 text-[0.82rem] font-medium text-text-secondary hover:text-foreground transition-colors"
                            >
                                {link.label}
                            </a>
                        ))}
                    </div>

                    {/* Desktop CTA */}
                    <div className="hidden md:flex items-center gap-4">
                        <Link
                            href="/signin"
                            className="text-[0.82rem] font-medium text-text-secondary hover:text-foreground transition-colors"
                        >
                            Sign In
                        </Link>
                        <Link
                            href="/signup"
                            className="px-4 py-2 text-[0.82rem] font-semibold text-white bg-primary rounded-lg hover:bg-primary-dark transition-colors"
                        >
                            Get Started
                        </Link>
                    </div>

                    {/* Mobile Menu Button */}
                    <button
                        onClick={() => setIsMobileOpen(!isMobileOpen)}
                        className="md:hidden p-2"
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

            {/* Mobile Menu */}
            <AnimatePresence>
                {isMobileOpen && (
                    <motion.div
                        initial={{ opacity: 0, height: 0 }}
                        animate={{ opacity: 1, height: "auto" }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.2 }}
                        className="md:hidden bg-white border-b border-[#f0f0f0] overflow-hidden"
                    >
                        <div className="px-6 py-4 space-y-1">
                            {navLinks.map((link) => (
                                <a
                                    key={link.label}
                                    href={link.href}
                                    onClick={() => setIsMobileOpen(false)}
                                    className="block px-3 py-2.5 text-sm text-text-secondary hover:text-foreground transition-colors"
                                >
                                    {link.label}
                                </a>
                            ))}
                            <div className="pt-3 mt-2 border-t border-[#f0f0f0] space-y-2">
                                <Link
                                    href="/signin"
                                    className="block px-3 py-2.5 text-sm text-text-secondary"
                                >
                                    Sign In
                                </Link>
                                <Link
                                    href="/signup"
                                    className="block w-full text-center px-3 py-2.5 text-sm font-semibold text-white bg-primary rounded-lg"
                                >
                                    Get Started
                                </Link>
                            </div>
                        </div>
                    </motion.div>
                )}
            </AnimatePresence>
        </motion.header>
    );
}
