import { NextResponse } from 'next/server'
// The client you can use to perform role-based access control (RBAC) or check
// if the user is logged in.
import { createServerClient } from '@supabase/ssr'
import { cookies } from 'next/headers'

// Only a same-origin relative path is a legitimate "next" — anything else (an
// absolute URL, a protocol-relative "//host" URL, or a "@host" userinfo trick)
// is an open-redirect attempt and falls back to the default.
function safeNextPath(next: string | null): string {
    if (!next || !next.startsWith('/') || next.startsWith('//')) {
        return '/dashboard'
    }
    return next
}

export async function GET(request: Request) {
    const { searchParams, origin } = new URL(request.url)
    const code = searchParams.get('code')
    const next = safeNextPath(searchParams.get('next'))

    if (code) {
        const cookieStore = await cookies()
        const supabase = createServerClient(
            process.env.NEXT_PUBLIC_SUPABASE_URL!,
            process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
            {
                cookies: {
                    getAll() {
                        return cookieStore.getAll()
                    },
                    setAll(cookiesToSet) {
                        try {
                            cookiesToSet.forEach(({ name, value, options }) =>
                                cookieStore.set(name, value, options)
                            )
                        } catch {
                            // The `setAll` method was called from a Server Component.
                            // This can be ignored if you have middleware refreshing
                            // user sessions.
                        }
                    },
                },
            }
        )
        const { error } = await supabase.auth.exchangeCodeForSession(code)
        if (!error) {
            return NextResponse.redirect(`${origin}${next}`)
        }
    }

    // return the user to an error page with instructions
    return NextResponse.redirect(`${origin}/signin?error=auth_callback_failed`)
}
