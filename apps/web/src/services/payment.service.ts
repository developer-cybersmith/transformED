import { api } from '@/lib/api';
import type { CreateOrderResponse, PaymentAccessResponse } from '@/types/payment';

export const paymentService = {
    // AC-1: no amount_paise sent -- the server ignores it anyway (S4-1 patch
    // 1, price-bypass fix) and sending it would misleadingly imply the
    // frontend controls price.
    createOrder: (lessonId: string) =>
        api
            .post<CreateOrderResponse>('payments/create-order', { lesson_id: lessonId })
            .then((r) => r.data),

    // D136 (docs/DEFECT-REGISTER.md): GET /api/payments/access does not exist
    // on the backend yet -- confirmed by reading
    // origin/razorpay-backend-endpoints-dev3's router.py directly, which
    // registers only create-order and webhook. Mocked here so the UI flow
    // (button -> modal -> poll -> redirect) is fully buildable and testable
    // now. The call site (useRazorpayCheckout) never changes when this is
    // swapped for a real `api.get(...)` call -- only this function's body
    // does.
    checkAccess: (_lessonId: string): Promise<PaymentAccessResponse> =>
        Promise.resolve({ has_access: true }),
};
