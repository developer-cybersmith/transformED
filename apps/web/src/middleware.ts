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

export async function middleware(request: NextRequest) {
    const { supabaseResponse, user } = await updateSession(request);
    const { pathname } = request.nextUrl;

    const isPublicRoute = PUBLIC_PATHS.has(pathname);

    if (!isPublicRoute && !user) {
        return NextResponse.redirect(new URL("/signin", request.url));
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
