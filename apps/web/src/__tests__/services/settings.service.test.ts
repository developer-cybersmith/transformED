/**
 * settingsService.updateNotifications — through the real axios instance via
 * MSW, not a mocked service function. No `vi.mock('@/lib/api')` anywhere:
 * this is what actually disconfirms AC-6 (no `user_id` in the body) and
 * AC-7 (never an empty body) at the point they'd matter -- the real
 * network call -- per docs/DEFECT-REGISTER.md binding rule 2.
 */
import { describe, it, expect } from 'vitest';
import { http, HttpResponse } from 'msw';
import { server } from '@/test/server';
import { API_BASE } from '@/test/handlers';
import { settingsService, singleFieldPatch } from '@/services/settings.service';

const NOTIFICATIONS_URL = `${API_BASE}/auth/notifications`;

describe('settingsService.updateNotifications (S3-07 AC-6, AC-7)', () => {
  it('sends a real PATCH with only the requested field, no user_id', async () => {
    let seenMethod: string | null = null;
    let seenBody: unknown = null;
    server.use(
      http.patch(NOTIFICATIONS_URL, async ({ request }) => {
        seenMethod = request.method;
        seenBody = await request.json();
        return HttpResponse.json({
          user_id: 'u1',
          session_report_email: true,
          lesson_ready_email: true,
          weekly_progress_email: true,
          streak_reminders: false,
          updated_at: '2026-08-06T12:00:00Z',
        });
      })
    );

    await settingsService.updateNotifications(singleFieldPatch('streak_reminders', false));

    expect(seenMethod).toBe('PATCH');
    expect(seenBody).toEqual({ streak_reminders: false });
    expect(seenBody).not.toHaveProperty('user_id');
  });

  it('resolves with the real response body, field-for-field', async () => {
    server.use(
      http.patch(NOTIFICATIONS_URL, () =>
        HttpResponse.json({
          user_id: 'u1',
          session_report_email: false,
          lesson_ready_email: true,
          weekly_progress_email: true,
          streak_reminders: true,
          updated_at: '2026-08-06T12:00:00Z',
        })
      )
    );

    const result = await settingsService.updateNotifications(singleFieldPatch('session_report_email', false));

    expect(result).toEqual({
      user_id: 'u1',
      session_report_email: false,
      lesson_ready_email: true,
      weekly_progress_email: true,
      streak_reminders: true,
      updated_at: '2026-08-06T12:00:00Z',
    });
  });

  it('rejects when the backend returns 422 (e.g. the empty-body case the type system now prevents at compile time)', async () => {
    server.use(
      http.patch(NOTIFICATIONS_URL, () =>
        HttpResponse.json({ detail: 'At least one notification preference field must be provided' }, { status: 422 })
      )
    );

    await expect(settingsService.updateNotifications(singleFieldPatch('streak_reminders', true))).rejects.toBeTruthy();
  });

  it('rejects on a 503 read-failure-style response from the backend', async () => {
    server.use(
      http.patch(NOTIFICATIONS_URL, () =>
        HttpResponse.json({ detail: 'Notification preferences temporarily unavailable' }, { status: 503 })
      )
    );

    await expect(settingsService.updateNotifications(singleFieldPatch('streak_reminders', true))).rejects.toBeTruthy();
  });
});
