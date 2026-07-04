"use client";

import React, { createContext, useContext, useEffect, useRef, useState } from "react";
import { createClient } from "@/lib/supabase/client";

type User = {
    id: string;
    email: string;
    full_name?: string;
    // Add other fields returned by FastAPI
};

type AuthContextType = {
    user: User | null;
    isLoading: boolean;
    error: string | null;
    refreshSession: () => Promise<void>;
    logout: () => Promise<void>;
};

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = useState<User | null>(null);
    const [isLoading, setIsLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const supabaseRef = useRef(createClient());

    const fetchSession = async () => {
        try {
            setIsLoading(true);
            setError(null);

            const { data, error: fetchError } = await supabaseRef.current.auth.getUser();

            if (fetchError || !data.user) throw fetchError;

            setUser({
                id: data.user.id,
                email: data.user.email!,
                full_name: data.user.user_metadata?.full_name
            });
        } catch (err) {
            setUser(null);
            // No active session or an expired one both land here — surface it as a
            // real error message instead of only a console.log, so a genuine outage
            // (vs. "you're just logged out") isn't silently indistinguishable.
            setError(err instanceof Error ? err.message : "No active session or session expired.");
        } finally {
            setIsLoading(false);
        }
    };

    const logout = async () => {
        try {
            await supabaseRef.current.auth.signOut();
        } catch (err) {
            console.error("Logout failed", err);
        } finally {
            // Fail closed: always clear local state and leave for /signin, even if the
            // remote signOut() call itself failed. Staying "logged in" client-side
            // after an intended logout is the wrong direction to fail in.
            setUser(null);
            window.location.href = "/signin";
        }
    };

    useEffect(() => {
        // Deferred to a microtask: fetchSession's setState calls run before its
        // first await, and calling it directly here would run them synchronously
        // within the effect body (cascading-render lint warning). Queuing it as a
        // callback instead matches the pattern of "subscribe, then setState from a
        // callback" that effects are meant to follow.
        Promise.resolve().then(fetchSession);

        // getUser() above is the authoritative initial check — it revalidates the
        // JWT against Supabase's auth server. onAuthStateChange's session payload is
        // read from local storage without server revalidation, so its INITIAL_SESSION
        // event is intentionally ignored here to avoid a race with fetchSession's
        // result; only *subsequent* events (SIGNED_IN, SIGNED_OUT, TOKEN_REFRESHED,
        // ...) are acted on, keeping `user` live across tab-based sign-in/out and
        // token refresh without requiring every consumer to call refreshSession().
        const {
            data: { subscription },
        } = supabaseRef.current.auth.onAuthStateChange((event, session) => {
            if (event === "INITIAL_SESSION") return;

            if (session?.user) {
                setUser({
                    id: session.user.id,
                    email: session.user.email!,
                    full_name: session.user.user_metadata?.full_name,
                });
            } else {
                setUser(null);
            }
            setIsLoading(false);
        });

        return () => {
            subscription.unsubscribe();
        };
    }, []);

    return (
        <AuthContext.Provider value={{ user, isLoading, error, refreshSession: fetchSession, logout }}>
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth() {
    const context = useContext(AuthContext);
    if (context === undefined) {
        throw new Error("useAuth must be used within an AuthProvider");
    }
    return context;
}
