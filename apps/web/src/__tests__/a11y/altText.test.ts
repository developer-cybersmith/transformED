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

// alt="" is the WCAG-correct pattern for a purely decorative image (it tells
// assistive tech to skip it, rather than announce a missing/unhelpful alt) --
// AvatarOverlay's loading-state placeholder thumbnail is exactly that case.
// Listed explicitly so it doesn't silently exempt anything else.
const ALLOWED_EMPTY_ALT = new Set(['../../components/player/AvatarOverlay.tsx']);

function extractImageTags(source: string): string[] {
  return source.match(/<(img|Image)\b[^>]*\/?>/g) ?? [];
}

// Requires whitespace immediately before "alt" so a decoy attribute like
// data-alt="x" can't satisfy the guard (review fix, S4-04) -- and reads the
// actual value so a bare `alt=""` (unless explicitly allowed above) still
// fails AC-2's "non-empty alt text" requirement, not just "alt is present".
// Handles both a string literal (`alt="..."`) and a JSX expression
// (`alt={...}`, e.g. `alt={title}` or a template literal) -- an expression's
// runtime value can't be statically evaluated here, so any expression other
// than an obviously-empty literal (`''`, `""`, ``` `` ```, `null`, `undefined`)
// is treated as non-empty.
function getAltValue(tag: string): string | null {
  const stringMatch = tag.match(/(?<=\s)alt\s*=\s*"([^"]*)"/);
  if (stringMatch) return stringMatch[1];

  const exprMatch = tag.match(/(?<=\s)alt\s*=\s*\{([^}]*)\}/);
  if (exprMatch) {
    const expr = exprMatch[1].trim();
    const emptyLiterals = new Set(["''", '""', '``', 'null', 'undefined', '']);
    return emptyLiterals.has(expr) ? '' : expr;
  }

  return null;
}

describe('AC-2: every <img>/<Image> has real alt text', () => {
  it.each(FILES_WITH_IMAGES)('%s', (relativePath) => {
    const source = readFileSync(join(__dirname, relativePath), 'utf-8');
    const tags = extractImageTags(source);

    expect(tags.length).toBeGreaterThan(0);
    for (const tag of tags) {
      const altValue = getAltValue(tag);
      expect(altValue).not.toBeNull();
      if (!ALLOWED_EMPTY_ALT.has(relativePath)) {
        expect(altValue).not.toBe('');
      }
    }
  });
});
