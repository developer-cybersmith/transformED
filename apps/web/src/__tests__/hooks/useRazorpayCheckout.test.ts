import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { renderHook, waitFor, act } from '@testing-library/react';
import {
    useRazorpayCheckout,
    PAYMENT_ACCESS_POLL_CEILING_MS,
    PAYMENT_ACCESS_POLL_INTERVAL_MS,
} from '@/hooks/useRazorpayCheckout';

// Review round (Scale & Load Hunter, Edge Case Hunter, Test Coverage): these
// four edge cases were flagged as either unguarded in the code or untested.
// Kept separate from RazorpayCheckoutButton.test.tsx -- these are state-
// machine concerns, not UI-rendering concerns, matching this repo's existing
// split (useLessonSocket.test.ts / useAttentionConsent.test.ts etc. all test
// their hook directly rather than only through a consuming component).

const { pushMock, createOrderMock, checkAccessMock } = vi.hoisted(() => ({
    pushMock: vi.fn(),
    createOrderMock: vi.fn(),
    checkAccessMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: pushMock }),
}));

vi.mock('@/services/payment.service', () => ({
    paymentService: {
        createOrder: createOrderMock,
        checkAccess: checkAccessMock,
    },
}));

const ORDER = { order_id: 'order_1', key_id: 'rzp_test_key', price_paise: 49900 };
const LESSON_ID = 'lesson-1';

let openMock: ReturnType<typeof vi.fn>;
let razorpayConstructorMock: ReturnType<typeof vi.fn>;

beforeEach(() => {
    pushMock.mockReset();
    createOrderMock.mockReset();
    checkAccessMock.mockReset();
    openMock = vi.fn();
    razorpayConstructorMock = vi.fn().mockImplementation(() => ({ open: openMock }));
    (window as unknown as { Razorpay: unknown }).Razorpay = razorpayConstructorMock;
});

afterEach(() => {
    vi.useRealTimers();
    delete (window as unknown as { Razorpay?: unknown }).Razorpay;
});

function getHandler(): (response: unknown) => void {
    return razorpayConstructorMock.mock.calls[0][0].handler;
}

describe('useRazorpayCheckout — re-entrancy guard', () => {
    it('a second start() call while an attempt is already in flight is a no-op (no second create-order)', async () => {
        createOrderMock.mockResolvedValue(ORDER);
        const { result } = renderHook(() => useRazorpayCheckout(LESSON_ID));

        // Both calls happen in the same tick, before the first status update
        // (creating_order) could disable a UI button -- this is exactly the
        // race the review found: two tabs, or a fast double-click landing
        // inside the same event-loop turn.
        act(() => {
            result.current.start();
            result.current.start();
        });

        await waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));
        expect(createOrderMock).toHaveBeenCalledTimes(1);
    });

    it('a fresh start() after a terminal error state is allowed (retry is not blocked by the guard)', async () => {
        createOrderMock.mockRejectedValueOnce({ response: { status: 500 } }).mockResolvedValueOnce(ORDER);
        const { result } = renderHook(() => useRazorpayCheckout(LESSON_ID));

        act(() => {
            result.current.start();
        });
        await waitFor(() => expect(result.current.status).toBe('error'));

        act(() => {
            result.current.start();
        });
        await waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));
        expect(createOrderMock).toHaveBeenCalledTimes(2);
    });
});

describe('useRazorpayCheckout — mid-poll failure', () => {
    it('a rejected checkAccess mid-poll surfaces the error state and never redirects', async () => {
        createOrderMock.mockResolvedValue(ORDER);
        checkAccessMock.mockRejectedValueOnce(new Error('network blip'));
        const { result } = renderHook(() => useRazorpayCheckout(LESSON_ID));

        act(() => {
            result.current.start();
        });
        await waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));
        act(() => {
            getHandler()({ razorpay_payment_id: 'pay_1', razorpay_order_id: ORDER.order_id, razorpay_signature: 'sig' });
        });

        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.errorMessage).toMatch(/contact support if you were charged/i);
        expect(pushMock).not.toHaveBeenCalled();
    });
});

describe('useRazorpayCheckout — unmount during poll', () => {
    it('unmounting mid-poll stops further checkAccess calls and never redirects afterward', async () => {
        createOrderMock.mockResolvedValue(ORDER);
        checkAccessMock.mockResolvedValue({ has_access: false });
        vi.useFakeTimers({ shouldAdvanceTime: true });

        const { result, unmount } = renderHook(() => useRazorpayCheckout(LESSON_ID));
        act(() => {
            result.current.start();
        });
        await act(async () => {
            await vi.waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));
        });
        act(() => {
            getHandler()({ razorpay_payment_id: 'pay_1', razorpay_order_id: ORDER.order_id, razorpay_signature: 'sig' });
        });
        await act(async () => {
            await vi.waitFor(() => expect(checkAccessMock).toHaveBeenCalledTimes(1));
        });

        const callsAtUnmount = checkAccessMock.mock.calls.length;
        act(() => {
            unmount();
        });

        await act(async () => {
            await vi.advanceTimersByTimeAsync(PAYMENT_ACCESS_POLL_CEILING_MS + PAYMENT_ACCESS_POLL_INTERVAL_MS);
        });

        expect(checkAccessMock).toHaveBeenCalledTimes(callsAtUnmount);
        expect(pushMock).not.toHaveBeenCalled();
    });
});

describe('useRazorpayCheckout — window.Razorpay unexpectedly missing', () => {
    it('surfaces a visible error instead of throwing when the global is missing at start() time', async () => {
        createOrderMock.mockResolvedValue(ORDER);
        // Simulates checkout.js reporting ready but the global having been
        // clobbered or never actually attaching -- distinct from the script
        // failing to load at all (that's RazorpayCheckoutButton's onError,
        // a component-level concern).
        delete (window as unknown as { Razorpay?: unknown }).Razorpay;

        const { result } = renderHook(() => useRazorpayCheckout(LESSON_ID));
        act(() => {
            result.current.start();
        });

        await waitFor(() => expect(result.current.status).toBe('error'));
        expect(result.current.errorMessage).toMatch(/please refresh and try again/i);
        expect(razorpayConstructorMock).not.toHaveBeenCalled();
    });
});
