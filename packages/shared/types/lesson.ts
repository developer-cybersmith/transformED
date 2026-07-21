// Sprint 0 interface contract — frozen
// Shared between FastAPI backend (mirrored in Pydantic) and Next.js frontend.
// Do not modify without updating the corresponding Pydantic models and JSON Schema.

export type LessonStatus = 'generating' | 'ready' | 'failed';

export type ComplexityLevel = 'low' | 'medium' | 'high';
export type AudioProvider = 'sarvam' | 'azure' | 'browser';
export type QuizType = 'mcq' | 'concept_check';
export type QuizDifficulty = 'easy' | 'medium' | 'hard';
export type LessonTier = 'T1' | 'T2' | 'T3';

export interface LessonMetadata {
  title: string;
  subject: string;
  total_segments: number;
  estimated_duration_mins: number;
  complexity_level: string;
  tier: LessonTier;
}

export interface SegmentComplexity {
  level: ComplexityLevel;
  cognitive_load: string;
  abstraction_level: string;
  prerequisite_concepts: string[];
  narration_style: string;
  quiz_difficulty: string;
  intervention_sensitivity: number; // 0–1
}

export interface Slide {
  slide_id: string;
  title: string;
  bullets: string[];
  image_url: string | null;
  fallback_image_url: string | null;
}

export interface NarrationTimestamp {
  slide_id: string;
  start_ms: number;
  end_ms: number;
}

export interface Narration {
  script: string;
  audio_url: string;
  audio_provider: AudioProvider;
  timestamps: NarrationTimestamp[];
}

export interface QuizQuestion {
  question_id: string;
  type: QuizType;
  question: string;
  options: string[];
  correct_index: number;
  explanation: string;
  difficulty: QuizDifficulty;
}

export interface JargonEntry {
  term: string;
  definition: string;
}

export interface SegmentInterventions {
  distraction: [string, string, string];
  confusion: [string, string, string];
  fatigue: [string, string, string];
}

export interface Segment {
  segment_id: string;
  segment_index: number;
  title: string;
  summary: string;
  complexity: SegmentComplexity;
  slides: Slide[];
  narration: Narration;
  quiz: QuizQuestion[];
  teachback_prompt: string;
  jargon: JargonEntry[];
  interventions: SegmentInterventions;
}

export interface GlossaryEntry {
  term: string;
  definition: string;
}

export interface LessonPackage {
  lesson_id: string;
  book_id: string;
  chapter_id: string;
  created_at: string;
  metadata: LessonMetadata;
  segments: Segment[];
  glossary: GlossaryEntry[];
}

/** DB row in the `lessons` table. `content` is a JSONB column. */
export interface LessonRecord {
  lesson_id: string;
  user_id: string;
  title: string;
  status: LessonStatus;
  content: LessonPackage | null;
  source_file_path: string;
  created_at: string;
  updated_at: string;
}
