"use client";

import { cn } from "@/lib/utils";
import React, { ReactNode } from "react";

interface AuroraBackgroundProps extends React.HTMLProps<HTMLDivElement> {
    children: ReactNode;
    showRadialGradient?: boolean;
}

export const AuroraBackground = ({
    className,
    children,
    showRadialGradient = true,
    ...props
}: AuroraBackgroundProps) => {
    return (
        <div
            className={cn(
                "relative flex flex-col items-center justify-center bg-white text-slate-950 transition-bg w-full",
                className
            )}
            {...props}
        >
            <div className="absolute inset-0 overflow-hidden">
                <div
                    className={cn(
                        `
          [--white-gradient:repeating-linear-gradient(100deg,var(--color-white)_0%,var(--color-white)_7%,transparent_10%,transparent_12%,var(--color-white)_16%)]
          [--aurora:repeating-linear-gradient(100deg,#DDE1E6_10%,#C6A45C_15%,#F3F5F8_20%,#E8D08D_25%,#DDE1E6_30%)]
          [background-image:var(--white-gradient),var(--aurora)]
          [background-size:300%,_200%]
          [background-position:50%_50%,50%_50%]
          filter blur-[10px]
          after:content-[''] after:absolute after:inset-0 after:[background-image:var(--white-gradient),var(--aurora)] 
          after:[background-size:200%,_100%] 
          after:animate-aurora after:[background-attachment:fixed]
          pointer-events-none
          absolute -inset-[10px] opacity-40 will-change-transform`,
                        showRadialGradient &&
                        `[mask-image:radial-gradient(ellipse_at_100%_0%,black_10%,transparent_70%)]`
                    )}
                ></div>
            </div>
            {children}
        </div>
    );
};
