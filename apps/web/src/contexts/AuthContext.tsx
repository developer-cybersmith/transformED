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

    // Lazy ref init: useRef(createClient()) would still evaluate createClient()
    // on every render (React only keeps the first *value*, not the first *call*),
    // needlessly constructing a new Supabase client each time. This pattern
    // guarantees createClient() runs exactly once.
    const supabaseRef = useRef<ReturnType<typeof createClient> | undefined>(undefined);
    if (supabaseRef.current == null) {
        supabaseRef.current = createClient();
    }
    const supabase = supabaseRef.current;

    const fetchSession = async () => {
        try {
            setIsLoading(true);
            setError(null);

            const { data, error: fetchError } = await supabase.auth.getUser();

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
            await supabase.auth.signOut();
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
        // Race guard: the mount-time getUser() call below is a real network round
        // trip and can resolve *after* a live onAuthStateChange event (e.g. a
        // SIGNED_OUT broadcast from another tab). Without this flag, that stale
        // resolution would silently overwrite the more recent, authoritative state
        // — e.g. showing a signed-out user as still logged in. Once any live event
        // fires, this mount-time check's result is discarded if it hasn't landed yet.
        let supersededByLiveEvent = false;

        Promise.resolve().then(async () => {
            try {
                setIsLoading(true);
                setError(null);

                const { data, error: fetchError } = await supabase.auth.getUser();
                if (supersededByLiveEvent) return;

                if (fetchError || !data.user) throw fetchError;

                setUser({
                    id: data.user.id,
                    email: data.user.email!,
                    full_name: data.user.user_metadata?.full_name,
                });
            } catch (err) {
                if (supersededByLiveEvent) return;
                setUser(null);
                setError(err instanceof Error ? err.message : "No active session or session expired.");
            } finally {
                if (!supersededByLiveEvent) setIsLoading(false);
            }
        });

        // getUser() above is the authoritative initial check — it revalidates the
        // JWT against Supabase's auth server. onAuthStateChange's session payload is
        // read from local storage without server revalidation, so its INITIAL_SESSION
        // event is intentionally ignored here to avoid a race with the mount-time
        // check's result; only *subsequent* events (SIGNED_IN, SIGNED_OUT,
        // TOKEN_REFRESHED, ...) are acted on, keeping `user` live across tab-based
        // sign-in/out and token refresh without requiring every consumer to call
        // refreshSession().
        const {
            data: { subscription },
        } = supabase.auth.onAuthStateChange((event, session) => {
            if (event === "INITIAL_SESSION") return;

            supersededByLiveEvent = true;

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
        // eslint-disable-next-line react-hooks/exhaustive-deps
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
