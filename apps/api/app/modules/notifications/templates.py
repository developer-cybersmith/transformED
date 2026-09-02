"""
Email template rendering for lesson-ready and session-report notifications
(Story 2-52).

Copy matches docs/bmad/epics/epic-5-platform-core.md's "Email Notifications"
section exactly ("Your lesson is ready! [Open Lesson]", "Here's how you did
— [View Report]"). Plain string templates, not a templating engine — two
static templates with three interpolated values total does not warrant a
new dependency (Jinja2 or similar).
"""

from __future__ import annotations

import html


def render_lesson_ready_email(*, lesson_title: str, lesson_url: str) -> tuple[str, str]:
    """Render the "lesson ready" email.

    Args:
        lesson_title: The lesson's display title (HTML-escaped before interpolation).
        lesson_url:   Full URL to the lesson player (e.g. f"{frontend_url}/lesson/{lesson_id}").

    Returns:
        A (subject, html) tuple.
    """
    safe_title = html.escape(lesson_title)
    subject = "Your lesson is ready!"
    body = f"""\
<!DOCTYPE html>
<html>
  <body style="font-family: sans-serif; color: #1a1a1a; max-width: 480px; margin: 0 auto;">
    <h2>Your lesson is ready!</h2>
    <p><strong>{safe_title}</strong> has finished generating and is ready to view.</p>
    <p>
      <a href="{lesson_url}" style="display: inline-block; padding: 12px 24px;
        background: #4f46e5; color: #ffffff; text-decoration: none; border-radius: 8px;">
        Open Lesson
      </a>
    </p>
  </body>
</html>
"""
    return subject, body


def render_session_report_email(*, lesson_title: str, report_url: str) -> tuple[str, str]:
    """Render the "session report" email.

    Args:
        lesson_title: The lesson's display title (HTML-escaped before interpolation).
        report_url:   Full URL to the session report (e.g. f"{frontend_url}/reports/{session_id}").

    Returns:
        A (subject, html) tuple.
    """
    safe_title = html.escape(lesson_title)
    subject = "Here's how you did"
    body = f"""\
<!DOCTYPE html>
<html>
  <body style="font-family: sans-serif; color: #1a1a1a; max-width: 480px; margin: 0 auto;">
    <h2>Here's how you did</h2>
    <p>Your session report for <strong>{safe_title}</strong> is ready.</p>
    <p>
      <a href="{report_url}" style="display: inline-block; padding: 12px 24px;
        background: #4f46e5; color: #ffffff; text-decoration: none; border-radius: 8px;">
        View Report
      </a>
    </p>
  </body>
</html>
"""
    return subject, body
