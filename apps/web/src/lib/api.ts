import axios from "axios";
import { createClient } from "@/lib/supabase/client";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000/api";

export const api = axios.create({
    baseURL: API_URL,
    headers: {
        "Content-Type": "application/json",
        "Accept": "application/json",
    },
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
