import axios from "axios";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export const api = axios.create({
    baseURL: API_URL,
    headers: {
        "Accept": "application/json",
    },
    // No default Content-Type here: axios auto-sets "application/json" for
    // plain-object bodies, but a FormData body (file uploads) needs axios to
    // generate its own multipart boundary — a hardcoded default header here
    // pre-empts that, so multipart requests are sent with no boundary at all
    // and the backend can't parse the file field (422).
});

api.interceptors.request.use(async (config) => {
    if (typeof window !== 'undefined') {
        const supabase = createClient();
        const { data } = await supabase.auth.getSession();
        if (data.session?.access_token) {
            config.headers.Authorization = `Bearer ${data.session.access_token}`;
        }
    }
    return config;
});

// Optional: Add response interceptor for global error handling
api.interceptors.response.use(
    (response) => response,
    (error) => {
        // Handle common errors like 401 Unauthorized globally if needed
        return Promise.reject(error);
    }
);
