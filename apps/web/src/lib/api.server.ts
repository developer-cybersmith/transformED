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
    const { data } = await supabase.auth.getSession();
    if (data.session?.access_token) {
        instance.defaults.headers.common.Authorization = `Bearer ${data.session.access_token}`;
    }

    return instance;
}
