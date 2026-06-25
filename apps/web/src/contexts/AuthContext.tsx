"use client";

import React, { createContext, useContext, useEffect, useState } from "react";
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

    const fetchSession = async () => {
        try {
            setIsLoading(true);
            setError(null);

            const supabase = createClient();
            const { data, error } = await supabase.auth.getUser();

            if (error || !data.user) throw error;

            setUser({
                id: data.user.id,
                email: data.user.email!,
                full_name: data.user.user_metadata?.full_name
            });
        } catch (err: any) {
            console.log("No active session or session expired.");
            setUser(null);
        } finally {
            setIsLoading(false);
        }
    };

    const logout = async () => {
        try {
            const supabase = createClient();
            await supabase.auth.signOut();
            setUser(null);
            window.location.href = "/signin";
        } catch (err) {
            console.error("Logout failed", err);
        }
    };

    useEffect(() => {
        fetchSession();
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
