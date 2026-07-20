import { NextResponse, type NextRequest } from "next/server";
import { updateSession } from "@/lib/supabase/middleware";

// Deny-list, not allow-list: everything not explicitly public requires a session.
// The previous allow-list only matched "/dashboard" and "/settings" — since
// /library and /upload live under the (dashboard) route group (invisible in the
// URL) and /onboarding, /lesson/[id] are separate top-level routes, all four
// were silently unauthenticated. A deny-list also fails safe for any future
// route that forgets to register itself here.
//
// /auth/callback MUST be public: it's the OAuth/email-confirmation code-exchange
// handler that runs *before* any session cookie exists. Gating it here means the
// handler never runs and every Google/email-link sign-in bounces back to /signin.
const PUBLIC_PATHS = new Set(["/", "/signin", "/signup", "/auth/callback"]);

// Routes that require a completed Learner DNA onboarding, in addition to a session.
// Only these two — gating /dashboard or /onboarding itself would strand the user
// (they'd never be able to reach the onboarding flow, or land anywhere after signin).
const ONBOARDING_GATED_PREFIXES = ["/lesson", "/upload"];

// Exact-segment match — a bare `startsWith` would also sweep in an unrelated
// future sibling route like `/lessons` or `/lesson-plans`.
function pathRequiresOnboarding(pathname: string): boolean {
    return ONBOARDING_GATED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export async function middleware(request: NextRequest) {
    const { supabaseResponse, user, supabase } = await updateSession(request);
    const { pathname } = request.nextUrl;

    const isPublicRoute = PUBLIC_PATHS.has(pathname);

    if (!isPublicRoute && !user) {
        return NextResponse.redirect(new URL("/signin", request.url));
    }

    if (user && pathRequiresOnboarding(pathname)) {
        try {
            const { data, error } = await supabase
                .from("learner_dna")
                .select("user_id")
                .eq("user_id", user.id)
                .maybeSingle();

            // Fail open: a transient DB/RLS error must not lock an already-onboarded
            // user out of /lesson and /upload — mirrors OnboardingFlow's own
            // mount-check policy of treating unexpected failures as non-blocking.
            if (!error && !data) {
                return NextResponse.redirect(new URL("/onboarding", request.url));
            }
        } catch {
            // Network/exception failure — fail open rather than crash middleware
            // for every /lesson and /upload request.
        }
    }

    return supabaseResponse;
}

export const config = {
    matcher: [
        /*
         * Match all request paths except for the ones starting with:
         * - _next/static (static files)
         * - _next/image (image optimization files)
         * - favicon.ico (favicon file)
         * Feel free to modify this pattern to include more paths.
         */
        "/((?!_next/static|_next/image|favicon.ico|.*\\.(?:svg|png|jpg|jpeg|gif|webp)$).*)",
    ],
};
