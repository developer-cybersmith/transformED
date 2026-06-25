import Link from "next/link";
import { BookOpen, Globe, Briefcase, Code2, Mail } from "lucide-react";
import Image from "next/image";

const footerSections = [
    {
        title: "Product",
        links: [
            { label: "Features", href: "#features" },
            { label: "Pricing", href: "#pricing" },
            { label: "How It Works", href: "#how-it-works" },
            { label: "FAQ", href: "#faq" },
        ],
    },
    {
        title: "Company",
        links: [
            { label: "About", href: "#" },
            { label: "Blog", href: "#" },
            { label: "Contact", href: "#" },
        ],
    },
    {
        title: "Legal",
        links: [
            { label: "Privacy", href: "#" },
            { label: "Terms", href: "#" },
        ],
    },
];

export default function Footer() {
    return (
        <footer className="border-t border-[#f0f0f0]">
            <div className="max-w-6xl mx-auto px-6 lg:px-8 py-14">
                <div className="grid grid-cols-2 md:grid-cols-5 gap-10">
                    {/* Brand */}
                    <div className="col-span-2">
                        <Link href="/" className="flex items-center gap-2 mb-3">
                            <Image src="/logo.jpeg" alt="HIE Logo" width={24} height={24} className="rounded-md object-contain" />
                            <span className="text-sm font-bold text-foreground font-display">
                                HIEIQ<span className="text-primary">.AI</span>
                            </span>
                        </Link>
                        <p className="text-xs text-text-muted leading-relaxed max-w-[240px]">
                            Human Intelligence Engine. Monitor cognitive decline and train your structural critical thinking, IQ, EQ, and SQ.
                        </p>
                    </div>

                    {/* Link Columns */}
                    {footerSections.map((section) => (
                        <div key={section.title}>
                            <h4 className="text-xs font-semibold text-foreground mb-3 uppercase tracking-wider">
                                {section.title}
                            </h4>
                            <ul className="space-y-2">
                                {section.links.map((link) => (
                                    <li key={link.label}>
                                        <a
                                            href={link.href}
                                            className="text-xs text-text-muted hover:text-foreground transition-colors"
                                        >
                                            {link.label}
                                        </a>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    ))}
                </div>

                <div className="mt-10 pt-6 border-t border-[#f0f0f0] text-xs text-text-muted">
                    © {new Date().getFullYear()} HIE. All rights reserved.
                </div>
            </div>
        </footer>
    );
}
