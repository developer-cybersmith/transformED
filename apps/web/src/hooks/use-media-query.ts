import { useCallback, useSyncExternalStore } from "react";

// useSyncExternalStore (not useState+useEffect) is the correct primitive here:
// matchMedia is an external, subscribable source that can also change when
// `query` itself changes — a plain effect would need to call setState directly
// in its body to resync on that case, which React's purity rules disallow.
export function useMediaQuery(query: string) {
    const subscribe = useCallback(
        (onStoreChange: () => void) => {
            const result = matchMedia(query);
            result.addEventListener("change", onStoreChange);
            return () => result.removeEventListener("change", onStoreChange);
        },
        [query]
    );

    const getSnapshot = useCallback(() => matchMedia(query).matches, [query]);
    const getServerSnapshot = () => false;

    return useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot);
}
