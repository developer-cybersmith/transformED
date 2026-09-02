import { describe, it, expect, vi, beforeEach } from 'vitest';
import { paymentService } from '@/services/payment.service';

const { postMock } = vi.hoisted(() => ({ postMock: vi.fn() }));

vi.mock('@/lib/api', () => ({
    api: { post: postMock },
}));

beforeEach(() => {
    postMock.mockReset();
});

describe('paymentService.createOrder', () => {
    it('AC-1: calls POST payments/create-order with only lesson_id — never amount_paise', async () => {
        postMock.mockResolvedValue({
            data: { order_id: 'order_1', key_id: 'rzp_test_key', price_paise: 49900 },
        });

        const result = await paymentService.createOrder('lesson-1');

        expect(postMock).toHaveBeenCalledWith('payments/create-order', { lesson_id: 'lesson-1' });
        expect(postMock.mock.calls[0][1]).not.toHaveProperty('amount_paise');
        expect(result).toEqual({ order_id: 'order_1', key_id: 'rzp_test_key', price_paise: 49900 });
    });

    it('propagates a rejected request so the caller can classify the failure (404 vs other)', async () => {
        const notFound = { response: { status: 404 } };
        postMock.mockRejectedValue(notFound);

        await expect(paymentService.createOrder('missing-lesson')).rejects.toBe(notFound);
    });
});

describe('paymentService.checkAccess (D136 — mocked, GET /api/payments/access does not exist yet)', () => {
    it('resolves has_access: true without calling the api client at all', async () => {
        const result = await paymentService.checkAccess('lesson-1');

        expect(result).toEqual({ has_access: true });
        expect(postMock).not.toHaveBeenCalled();
    });
});
