// Story 2-53 (S4-02). Shapes match the real (unmerged) backend branch
// `razorpay-backend-endpoints-dev3` -- apps/api/app/modules/payments/schemas.py
// -- read directly rather than assumed from the cross-team integration
// message.

export interface CreateOrderResponse {
    order_id: string;
    key_id: string;
    price_paise: number;
}

// D136 (docs/DEFECT-REGISTER.md): GET /api/payments/access does not exist on
// the backend yet. This shape is what the cross-team spec says it will
// return once built -- kept here so the eventual real call site changes
// nothing but payment.service.ts's own implementation.
export interface PaymentAccessResponse {
    has_access: boolean;
}

// The subset of Razorpay's checkout.js handler payload this app actually
// uses. Not sent anywhere by the frontend -- Razorpay's own webhook (server
// to server) is the source of truth for fulfillment; this is informational
// only, used to know "the modal reported success, start polling for access."
export interface RazorpayHandlerResponse {
    razorpay_payment_id: string;
    razorpay_order_id: string;
    razorpay_signature: string;
}
