import { describe, it, expect, vi } from 'vitest';

vi.mock('@/components/player/PlayerLoader', () => ({
  PlayerLoader: () => null,
}));

import LessonPage from '@/app/lesson/[id]/page';

describe('LessonPage', () => {
  it('keys PlayerLoader by lessonId, so navigating between two lessons remounts it instead of reusing a stale useLesson instance (S4-11)', async () => {
    const element = (await LessonPage({ params: Promise.resolve({ id: 'lsn_42' }) })) as {
      props: { children: { key: string | null; props: { lessonId: string } } };
    };

    const playerLoaderElement = element.props.children;
    expect(playerLoaderElement.key).toBe('lsn_42');
    expect(playerLoaderElement.props.lessonId).toBe('lsn_42');
  });
});
