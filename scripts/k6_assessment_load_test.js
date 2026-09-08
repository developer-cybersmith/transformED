/**
 * k6 load test — Assessment API concurrent user test (Story 4-30, AC 14–16)
 *
 * Simulates 20–50 concurrent virtual users going through a full student session:
 *   POST /api/assessment/sessions
 *   POST /api/assessment/quiz  (×4 questions)
 *   POST /api/assessment/teachback
 *   GET  /api/assessment/session/{id}/report
 *
 * Usage:
 *   k6 run --env BASE_URL=https://your-api.railway.app \
 *          --env AUTH_TOKEN=your-jwt-token \
 *          scripts/k6_assessment_load_test.js
 *
 * Install k6: https://k6.io/docs/get-started/installation/
 */

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// ---------------------------------------------------------------------------
// Configuration
// ---------------------------------------------------------------------------
const BASE_URL    = __ENV.BASE_URL    || 'http://localhost:8000';
const AUTH_TOKEN  = __ENV.AUTH_TOKEN  || '';
const LESSON_ID   = __ENV.LESSON_ID   || '00000000-0000-0000-0000-000000000001';

export const options = {
  stages: [
    { duration: '30s', target: 10  },  // ramp up
    { duration: '60s', target: 30  },  // steady load (30 concurrent users)
    { duration: '30s', target: 50  },  // peak load (50 concurrent users)
    { duration: '30s', target: 0   },  // ramp down
  ],
  thresholds: {
    http_req_duration:              ['p(95)<2000'],   // p95 < 2s
    http_req_failed:                ['rate<0.01'],    // < 1% error rate
    'http_req_duration{endpoint:quiz}':       ['p(95)<2000'],
    'http_req_duration{endpoint:teachback}':  ['p(95)<5000'],  // LLM call — allow 5s
    'http_req_duration{endpoint:report}':     ['p(95)<1000'],
  },
};

// Custom metrics
const quizErrors     = new Counter('quiz_errors');
const teachbackErrors = new Counter('teachback_errors');
const sessionErrors   = new Counter('session_errors');
const cesScores       = new Trend('ces_scores');

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
function headers() {
  return {
    'Content-Type': 'application/json',
    Authorization: `Bearer ${AUTH_TOKEN}`,
  };
}

function randomTeachback() {
  const responses = [
    "Photosynthesis is the process by which plants convert sunlight into glucose using carbon dioxide and water.",
    "Newton's third law states that for every action there is an equal and opposite reaction.",
    "Mitosis is cell division that produces two genetically identical daughter cells.",
    "The water cycle involves evaporation, condensation, and precipitation.",
    "DNA carries genetic information using four nucleotide bases: adenine, thymine, guanine, cytosine.",
  ];
  return responses[Math.floor(Math.random() * responses.length)];
}

// ---------------------------------------------------------------------------
// Main scenario
// ---------------------------------------------------------------------------
export default function () {
  const vuId = `vu-${__VU}-${__ITER}`;

  // --- 1. Create session ------------------------------------------------
  const sessionRes = http.post(
    `${BASE_URL}/api/assessment/sessions`,
    JSON.stringify({ lesson_id: LESSON_ID }),
    { headers: headers(), tags: { endpoint: 'session' } },
  );

  const sessionOk = check(sessionRes, {
    'session created: status 201': (r) => r.status === 201 || r.status === 200,
    'session has id': (r) => {
      try { return !!JSON.parse(r.body).session_id; } catch { return false; }
    },
  });

  if (!sessionOk) {
    sessionErrors.add(1);
    console.error(`[${vuId}] Session creation failed: ${sessionRes.status} ${sessionRes.body}`);
    return;
  }

  const sessionId = JSON.parse(sessionRes.body).session_id;
  sleep(0.5);

  // --- 2. Submit 4 quiz questions (single batch POST, matches QuizSubmission) --
  const QUESTION_IDS = ['q-1', 'q-2', 'q-3', 'q-4'];
  const quizRes = http.post(
    `${BASE_URL}/api/assessment/quiz`,
    JSON.stringify({
      session_id: sessionId,
      lesson_id: LESSON_ID,
      segment_id: 'seg-1',
      answers: QUESTION_IDS.map((questionId) => ({
        question_id: questionId,
        response_index: Math.floor(Math.random() * 4),
        response_time_ms: Math.floor(Math.random() * 15000) + 2000,
      })),
    }),
    { headers: headers(), tags: { endpoint: 'quiz' } },
  );

  const quizOk = check(quizRes, {
    'quiz: status 200': (r) => r.status === 200,
    'quiz: has ces_contribution': (r) => {
      try { return 'ces_contribution' in JSON.parse(r.body); } catch { return false; }
    },
  });

  if (!quizOk) {
    quizErrors.add(1);
    console.warn(`[${vuId}] Quiz submission failed: ${quizRes.status} ${quizRes.body}`);
  }
  sleep(0.2);

  // --- 3. Submit teachback (50% of VUs) ------------------------------------
  if (__VU % 2 === 0) {
    const tbRes = http.post(
      `${BASE_URL}/api/assessment/teachback`,
      JSON.stringify({
        session_id: sessionId,
        lesson_id: LESSON_ID,
        segment_id: 'seg-1',
        response_text: randomTeachback(),
      }),
      { headers: headers(), tags: { endpoint: 'teachback' } },
    );

    const tbOk = check(tbRes, {
      'teachback: status 200': (r) => r.status === 200,
      'teachback: has overall_score': (r) => {
        try { return 'overall_score' in JSON.parse(r.body); } catch { return false; }
      },
    });

    if (!tbOk) {
      teachbackErrors.add(1);
      console.warn(`[${vuId}] Teachback failed: ${tbRes.status}`);
    }
    sleep(1.0);
  }

  // --- 4. Complete session -----------------------------------------------
  http.post(
    `${BASE_URL}/api/assessment/session/${sessionId}/complete`,
    null,
    { headers: headers(), tags: { endpoint: 'complete' } },
  );
  sleep(0.3);

  // --- 5. Get session report --------------------------------------------
  const reportRes = http.get(
    `${BASE_URL}/api/assessment/session/${sessionId}/report`,
    { headers: headers(), tags: { endpoint: 'report' } },
  );

  const reportOk = check(reportRes, {
    'report: status 200': (r) => r.status === 200,
    'report: has ces_score': (r) => {
      try { return 'ces_score' in JSON.parse(r.body); } catch { return false; }
    },
  });

  if (reportOk) {
    try {
      const body = JSON.parse(reportRes.body);
      if (typeof body.ces_score === 'number') {
        cesScores.add(body.ces_score);
      }
    } catch {}
  }

  sleep(Math.random() * 2 + 1);  // think time 1–3s between iterations
}
