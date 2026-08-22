import { test, expect } from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';

/**
 * Accessibility checks for the shell (FR-047a, FR-047b, SC-015).
 *
 * FR-047b is unusually explicit that automated rules prove only part of the baseline:
 * axe catches missing labels, roles and alt text, but cannot judge whether a flow is
 * keyboard-operable or whether focus is visible. The keyboard tests below close as
 * much of that gap as automation can; the rest stays a reviewer's job, by design.
 */

test.describe('application shell accessibility', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
  });

  test('has no automatically detectable accessibility violations', async ({ page }) => {
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
      .analyze();

    // Report every violation, not just the count -- "3 violations" is not actionable.
    expect(
      results.violations,
      results.violations.map((v) => `${v.id}: ${v.help}`).join('\n'),
    ).toEqual([]);
  });

  test('exposes exactly one h1', async ({ page }) => {
    await expect(page.locator('h1')).toHaveCount(1);
  });

  test('landmarks are present and labelled', async ({ page }) => {
    await expect(page.locator('header')).toBeVisible();
    await expect(page.locator('main#main-content')).toBeVisible();
    await expect(page.getByRole('navigation', { name: 'Primary' })).toBeVisible();
  });

  test('the skip link is the first focusable element and becomes visible', async ({ page }) => {
    await page.keyboard.press('Tab');
    const focused = page.locator(':focus');
    await expect(focused).toHaveText(/skip to main content/i);
    // Visually hidden until focused -- it must not be display:none, or a keyboard
    // user can never reach it.
    await expect(focused).toBeVisible();
  });

  test('the skip link moves focus to main content', async ({ page }) => {
    await page.keyboard.press('Tab');
    await page.keyboard.press('Enter');
    await expect(page.locator('#main-content')).toBeFocused();
  });

  test('every interactive control is reachable by keyboard alone', async ({ page }) => {
    // FR-047a: keyboard operability. A control reachable only by mouse is invisible
    // to a keyboard or screen-reader user.
    const interactive = await page.locator('a[href], button, [tabindex]:not([tabindex="-1"])').count();
    const reached = new Set<string>();

    for (let i = 0; i < interactive + 2; i++) {
      await page.keyboard.press('Tab');
      const tag = await page.evaluate(() => {
        const el = document.activeElement;
        return el ? `${el.tagName}:${el.textContent?.trim().slice(0, 24) ?? ''}` : '';
      });
      if (tag) reached.add(tag);
    }

    expect(reached.size).toBeGreaterThanOrEqual(interactive);
  });

  test('the focused control has a visible focus indicator', async ({ page }) => {
    await page.keyboard.press('Tab');
    const outline = await page.evaluate(() => {
      const el = document.activeElement;
      if (!el) return null;
      const s = getComputedStyle(el);
      return { width: s.outlineWidth, style: s.outlineStyle };
    });
    // FR-047a requires focus to be *visible*. `outline: none` with no replacement is
    // the single most common way this baseline is broken.
    expect(outline).not.toBeNull();
    expect(outline!.style).not.toBe('none');
  });
});
