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
const PUBLIC_PATHS = new Set(["/", "/signin", "/signup", "/auth/callback", "/pending-approval"]);

// Beta access gate: self-serve signup is open, but /upload and /onboarding
// both trigger real OpenAI spend on the backend with no cost gate of their
// own -- an unapproved signup could otherwise run up real API cost. Checked
// server-side here (this closes it off entirely) AND in the backend's own
// require_approved_user dependency (the actual boundary -- this proxy alone
// is bypassable by anyone calling the API directly with their own valid JWT).
//
// Same env var name as the backend's APPROVED_EMAILS (config.py) -- this is
// a separate, deliberately duplicated copy, not NEXT_PUBLIC_ (never exposed
// to the browser bundle, only read here in the server-only proxy). The
// frontend talks to Supabase directly and has no dependency on the backend
// being deployed/reachable, so it can't check a shared source of truth
// without introducing that dependency. Keep both copies in sync manually
// for now -- see docs/DEPLOYMENT-OPS-NOTES.md.
//
// An empty allowlist means every user gets redirected to /pending-approval
// -- this is a security/cost boundary, not a UX nicety, so an unset env var
// must never silently mean "let everyone through" (fail closed, matching
// the backend's require_approved_user exactly).
//
// Re-parsed on every call rather than cached at module scope: this env var
// never changes at runtime in production, but a module-scope constant would
// snapshot process.env.APPROVED_EMAILS at first import and never see a
// value set later (e.g. via vi.stubEnv in tests). The parse cost is a few
// microseconds on a short comma-separated string -- not worth trading away
// testability for.
function getApprovedEmails(): Set<string> {
    return new Set(
        (process.env.APPROVED_EMAILS ?? "")
            .split(",")
            .map((email) => email.trim().toLowerCase())
            .filter(Boolean)
    );
}

// Routes that require a completed Learner DNA onboarding, in addition to a session.
// Only these — gating /dashboard or /onboarding itself would strand the user
// (they'd never be able to reach the onboarding flow, or land anywhere after signin).
// "/books" covers both /books and /books/{id} via the exact-segment match below.
const ONBOARDING_GATED_PREFIXES = ["/lesson", "/upload", "/books"];

// Exact-segment match — a bare `startsWith` would also sweep in an unrelated
// future sibling route like `/lessons` or `/lesson-plans`.
function pathRequiresOnboarding(pathname: string): boolean {
    return ONBOARDING_GATED_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
}

export async function proxy(request: NextRequest) {
    const { supabaseResponse, user, supabase } = await updateSession(request);
    const { pathname } = request.nextUrl;

    const isPublicRoute = PUBLIC_PATHS.has(pathname);

    if (!isPublicRoute && !user) {
        return NextResponse.redirect(new URL("/signin", request.url));
    }

    // Checked before the onboarding gate below: onboarding itself calls an
    // LLM (Learner DNA generation) on submit, so an unapproved user must
    // never reach it either, not just /lesson and /upload.
    if (!isPublicRoute && user) {
        const email = (user.email ?? "").toLowerCase();
        if (!getApprovedEmails().has(email)) {
            return NextResponse.redirect(new URL("/pending-approval", request.url));
        }
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
            // Network/exception failure — fail open rather than crash proxy
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
