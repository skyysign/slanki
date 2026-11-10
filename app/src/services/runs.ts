// Generation run records with the same defaults as the Django GenerationRun model.
import { newUuid } from "../core/ids.ts";
import { nowIso, type StoredRun } from "../store/library.ts";

export function newRun(lectureId: string, fields: Partial<StoredRun>): StoredRun {
  const now = nowIso();
  return {
    id: newUuid(),
    status: "queued",
    provider: "codex",
    model: "",
    page_numbers: [],
    completed_pages: [],
    context_enabled: false,
    context_data: {},
    text_enabled: true,
    occlusion_enabled: false,
    visual_enabled: false,
    purpose: "cards",
    rundown_data: {},
    image_completed_pages: [],
    suggestions: [],
    issues: [],
    cards_added: 0,
    study_cards_added: 0,
    learning_focus: "balanced",
    card_format: "basic",
    card_limit: null,
    reasoning_effort: "",
    filtered_count: 0,
    over_limit_count: 0,
    error: "",
    created_at: now,
    updated_at: now,
    ...fields,
    lecture_id: lectureId,
  };
}
