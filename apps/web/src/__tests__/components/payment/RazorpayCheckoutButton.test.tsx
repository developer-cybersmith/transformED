import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useEffect } from 'react';
import { RazorpayCheckoutButton } from '@/components/payment/RazorpayCheckoutButton';
import {
    PAYMENT_ACCESS_POLL_INTERVAL_MS,
    PAYMENT_ACCESS_POLL_CEILING_MS,
} from '@/hooks/useRazorpayCheckout';

const { pushMock, createOrderMock, checkAccessMock } = vi.hoisted(() => ({
    pushMock: vi.fn(),
    createOrderMock: vi.fn(),
    checkAccessMock: vi.fn(),
}));

vi.mock('next/navigation', () => ({
    useRouter: () => ({ push: pushMock }),
}));

// AC-2: checkout.js is loaded via next/script — stubbed here to fire
// onReady on mount (Turnstile.tsx's own precedent: Next.js guarantees this
// on every mount, cached or not, so no extra "already loaded" branch to
// test separately).
function MockScript({ onReady }: { onReady?: () => void }) {
    useEffect(() => {
        onReady?.();
    }, [onReady]);
    return null;
}

vi.mock('next/script', () => ({
    default: MockScript,
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

describe('RazorpayCheckoutButton', () => {
    it('AC-1/AC-2: click -> create-order -> opens Razorpay modal with the real order fields, no amount_paise override', async () => {
        const user = userEvent.setup();
        createOrderMock.mockResolvedValue(ORDER);
        render(<RazorpayCheckoutButton lessonId={LESSON_ID} />);

        await user.click(await screen.findByRole('button', { name: /buy lesson/i }));

        await waitFor(() => expect(createOrderMock).toHaveBeenCalledWith(LESSON_ID));
        await waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));

        const options = razorpayConstructorMock.mock.calls[0][0];
        expect(options).toMatchObject({
            key: ORDER.key_id,
            order_id: ORDER.order_id,
            amount: ORDER.price_paise,
            currency: 'INR',
        });
        expect(openMock).toHaveBeenCalledTimes(1);
    });

    it('AC-3: on payment success, polls checkAccess and redirects to the lesson player once has_access is true', async () => {
        createOrderMock.mockResolvedValue(ORDER);
        checkAccessMock.mockResolvedValueOnce({ has_access: false }).mockResolvedValueOnce({ has_access: true });
        vi.useFakeTimers({ shouldAdvanceTime: true });

        render(<RazorpayCheckoutButton lessonId={LESSON_ID} />);
        await userEvent.setup({ delay: null }).click(screen.getByRole('button', { name: /buy lesson/i }));

        await vi.waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));
        act(() => {
            getHandler()({ razorpay_payment_id: 'pay_1', razorpay_order_id: ORDER.order_id, razorpay_signature: 'sig' });
        });

        await vi.waitFor(() => expect(checkAccessMock).toHaveBeenCalledTimes(1));
        await vi.advanceTimersByTimeAsync(PAYMENT_ACCESS_POLL_INTERVAL_MS);
        await vi.waitFor(() => expect(checkAccessMock).toHaveBeenCalledTimes(2));
        await vi.waitFor(() => expect(pushMock).toHaveBeenCalledWith(`/lesson/${LESSON_ID}`));
    });

    it('AC-3/Scale&Load Q2: past the poll ceiling, surfaces an explicit timeout state — never silent, never a false success', async () => {
        createOrderMock.mockResolvedValue(ORDER);
        checkAccessMock.mockResolvedValue({ has_access: false });
        vi.useFakeTimers({ shouldAdvanceTime: true });

        render(<RazorpayCheckoutButton lessonId={LESSON_ID} />);
        await userEvent.setup({ delay: null }).click(screen.getByRole('button', { name: /buy lesson/i }));
        await vi.waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));
        act(() => {
            getHandler()({ razorpay_payment_id: 'pay_1', razorpay_order_id: ORDER.order_id, razorpay_signature: 'sig' });
        });

        await act(async () => {
            await vi.advanceTimersByTimeAsync(PAYMENT_ACCESS_POLL_CEILING_MS + PAYMENT_ACCESS_POLL_INTERVAL_MS);
        });

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toMatch(/taking longer than expected/i);
        expect(pushMock).not.toHaveBeenCalled();
    });

    it('AC-1: a 404 from create-order (lesson not found) surfaces a specific, visible error', async () => {
        const user = userEvent.setup();
        createOrderMock.mockRejectedValue({ response: { status: 404 } });
        render(<RazorpayCheckoutButton lessonId={LESSON_ID} />);

        await user.click(await screen.findByRole('button', { name: /buy lesson/i }));

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toMatch(/could not be found/i);
        expect(razorpayConstructorMock).not.toHaveBeenCalled();
    });

    it('AC-1: a generic (500) create-order failure surfaces a visible, non-crashing error', async () => {
        const user = userEvent.setup();
        createOrderMock.mockRejectedValue({ response: { status: 500 } });
        render(<RazorpayCheckoutButton lessonId={LESSON_ID} />);

        await user.click(await screen.findByRole('button', { name: /buy lesson/i }));

        const alert = await screen.findByRole('alert');
        expect(alert.textContent).toMatch(/try again/i);
    });

    it('AC-5: closing the modal without paying (ondismiss) returns to the pre-click state, no cancel page', async () => {
        const user = userEvent.setup();
        createOrderMock.mockResolvedValue(ORDER);
        render(<RazorpayCheckoutButton lessonId={LESSON_ID} />);

        await user.click(await screen.findByRole('button', { name: /buy lesson/i }));
        await waitFor(() => expect(razorpayConstructorMock).toHaveBeenCalledTimes(1));

        const options = razorpayConstructorMock.mock.calls[0][0];
        act(() => {
            options.modal.ondismiss();
        });

        await waitFor(() => {
            const button = screen.getByRole('button', { name: /buy lesson/i }) as HTMLButtonElement;
            expect(button.disabled).toBe(false);
        });
        expect(pushMock).not.toHaveBeenCalled();
    });
});
