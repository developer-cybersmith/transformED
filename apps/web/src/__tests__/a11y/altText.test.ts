import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect } from 'vitest';

// AC-2: guard against a future regression, since no eslint-plugin-jsx-a11y is
// configured in this repo to catch it automatically (docs/stories/2-55).
// Every <img>/<Image> usage found in the codebase at audit time is listed
// here explicitly -- a new image component must be added to this list, which
// itself forces a deliberate look at whether it has real alt text.
const FILES_WITH_IMAGES = [
  '../../app/pending-approval/page.tsx',
  '../../components/layout/Navbar.tsx',
  '../../components/layout/Footer.tsx',
  '../../components/player/AvatarOverlay.tsx',
  '../../components/dashboard/shell/TopUtilityBar.tsx',
  '../../components/sections/Features.tsx',
  '../../components/dashboard/shell/Sidebar.tsx',
  '../../components/player/SlideRenderer.tsx',
  '../../app/(auth)/signin/page.tsx',
  '../../app/(auth)/signup/page.tsx',
  '../../components/settings/tabs/ProfileTab.tsx',
];

function extractImageTags(source: string): string[] {
  return source.match(/<(img|Image)\b[^>]*\/?>/g) ?? [];
}

describe('AC-2: every <img>/<Image> has an alt attribute', () => {
  it.each(FILES_WITH_IMAGES)('%s', (relativePath) => {
    const source = readFileSync(join(__dirname, relativePath), 'utf-8');
    const tags = extractImageTags(source);

    expect(tags.length).toBeGreaterThan(0);
    for (const tag of tags) {
      expect(tag).toMatch(/\balt=/);
    }
  });
});
