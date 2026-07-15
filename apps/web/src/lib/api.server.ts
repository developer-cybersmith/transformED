import axios from "axios";
import { createClient } from "@/lib/supabase/server";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

// Server-only counterpart to `lib/api.ts` — that instance's auth interceptor
// only attaches the JWT `if (typeof window !== 'undefined')`, so it silently
// sends no Authorization header when called from a Server Component. This
// reads the session via the cookie-based server Supabase client instead.
// Must never be imported from a "use client" file (pulls in next/headers).
export async function getServerApi() {
    const instance = axios.create({
        baseURL: API_URL,
        headers: { Accept: "application/json" },
    });

    const supabase = await createClient();

    // getUser() re-validates the session against the Supabase Auth server —
    // getSession() alone only reads the cookie payload back, which can still
    // "succeed" for a stale/revoked session (a known Supabase SSR footgun).
    // Only fetch the actual token once a genuinely valid user is confirmed.
    const { data: userData, error: userError } = await supabase.auth.getUser();
    if (!userError && userData.user) {
        const { data: sessionData } = await supabase.auth.getSession();
        if (sessionData.session?.access_token) {
            instance.defaults.headers.common.Authorization = `Bearer ${sessionData.session.access_token}`;
        }
    }

    return instance;
}
