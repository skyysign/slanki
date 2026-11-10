// Backup manifest validation and upgrade (port of backups.py restore_backup).
// Records keep the Recalloom format-12 field names so Slanki backups stay
// lossless: study guides, image suggestions and run history pass through even
// though Slanki no longer shows them.
import { validateContent } from "../core/cards.ts";
import { WorkflowError } from "../core/errors.ts";
import { checkedCrop, checkedOcclusion, checkedVisualMasks, type Crop, type Mask } from "../core/geometry.ts";
import { isUuid } from "../core/ids.ts";
import { CARD_FORMATS, LEARNING_FOCUSES, NOTE_TYPES } from "../core/noteTypes.ts";
import { checkedContext } from "../core/overview.ts";
import { cpLength, hasExactKeys, isInt, isPlainObject } from "../core/py.ts";
import { compareNewest, compareNotes } from "../core/time.ts";

export const MAX_PAGES = 100;
export const RECALLOOM_FORMAT = "slides-to-anki";
export const SLANKI_FORMAT = "slanki";
export const SLANKI_VERSION = 1;

export const EFFORTS = ["", "none", "minimal", "low", "medium", "high", "xhigh", "max", "off", "on"] as const;
const MODEL_ID = /^[A-Za-z0-9][A-Za-z0-9._:/[\]-]{0,99}$/;

export interface LectureRecord {
  id: string;
  title: string;
  sha256: string;
  original_name: string;
  created_at: string;
}

export interface PageRecord {
  number: number;
  text: string;
  width: number;
  height: number;
  warning: string;
}

export interface RevisionRecord {
  version: number;
  front: string;
  note_type: string;
  visual_masks: Mask[];
  back: string;
  source_quote: string;
  source_crop: Crop | Record<string, never>;
  occlusion: Mask | Record<string, never>;
  status: string;
  created_at: string;
}

export interface CardRecord {
  id: string;
  page: number;
  front: string;
  note_type: (typeof NOTE_TYPES)[number];
  back: string;
  source_quote: string;
  source_crop: Crop | Record<string, never>;
  occlusion: Mask | Record<string, never>;
  visual_masks: Mask[];
  status: "draft" | "accepted" | "rejected";
  fingerprint: string;
  version: number;
  anki_modified: number;
  run: string | null;
  created_at: string;
  updated_at: string;
  revisions: RevisionRecord[];
}

export interface RunRecord {
  id: string;
  status: string;
  provider: string;
  model: string;
  page_numbers: number[];
  completed_pages: number[];
  context_enabled: boolean;
  context_data: Record<string, unknown>;
  text_enabled: boolean;
  occlusion_enabled: boolean;
  visual_enabled: boolean;
  purpose: string;
  rundown_data: Record<string, unknown>;
  image_completed_pages: number[];
  suggestions: Record<string, unknown>[];
  issues: Record<string, unknown>[];
  cards_added: number;
  study_cards_added: number;
  learning_focus: string;
  card_format: string;
  card_limit: number | null;
  reasoning_effort: string;
  filtered_count: number;
  over_limit_count: number;
  error: string;
  created_at: string;
  updated_at: string;
}

export interface Manifest {
  format: string;
  version: number;
  lecture: LectureRecord;
  pages: PageRecord[];
  cards: CardRecord[];
  runs: RunRecord[];
  assets: Record<string, string>;
}

const invalid = (message = "Backup contains an invalid record structure.") => new WorkflowError(message);

function requireKeys(value: unknown, names: string): asserts value is Record<string, unknown> {
  if (!hasExactKeys(value, names.split(" "))) throw invalid();
}

const TIMESTAMP = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d{1,6})?)?(Z|[+-]\d{2}(:?\d{2})?)$/;

function timestamp(value: unknown): string {
  if (typeof value !== "string" || !TIMESTAMP.test(value) || Number.isNaN(Date.parse(value.replace(" ", "T")))) {
    throw new WorkflowError("Backup contains an invalid timestamp.");
  }
  return value;
}

function text(value: unknown, max: number, { blank = true } = {}): string {
  if (typeof value !== "string" || cpLength(value) > max || (!blank && !value)) throw invalid();
  return value;
}

function positive(value: unknown): number {
  if (!isInt(value) || value < 0) throw invalid();
  return value;
}

function validateRunPages(numbers: unknown, allowed: ReadonlySet<number> | readonly number[]): number[] {
  const set = allowed instanceof Set ? allowed : new Set(allowed as readonly number[]);
  if (
    !Array.isArray(numbers) ||
    numbers.some((number) => !isInt(number) || !set.has(number)) ||
    new Set(numbers).size !== numbers.length
  ) {
    throw new WorkflowError("Backup contains invalid generation page references.");
  }
  return numbers as number[];
}

function validateRunIssues(issues: unknown, pageNumbers: number[]): Record<string, unknown>[] {
  if (!Array.isArray(issues) || issues.length > 500 * MAX_PAGES) {
    throw new WorkflowError("Backup contains invalid generation issues.");
  }
  for (const issue of issues) {
    requireKeys(issue, "page batch_pages reason front back source_quote");
    const batch = validateRunPages(issue.batch_pages, pageNumbers);
    if (issue.page !== null) validateRunPages([issue.page], batch);
    for (const [key, limit] of [
      ["reason", 1000],
      ["front", 1000],
      ["back", 5000],
      ["source_quote", 2500],
    ] as const) {
      const value = issue[key];
      if (typeof value !== "string" || cpLength(value) > limit || value.includes("\x00")) {
        throw new WorkflowError("Backup contains an invalid generation issue.");
      }
    }
  }
  return issues;
}

function runKeys(version: number): string {
  return (
    "id status provider page_numbers completed_pages cards_added error created_at updated_at" +
    (version >= 2 ? " issues" : "") +
    (version >= 3 ? " card_limit filtered_count over_limit_count" : "") +
    (version >= 4 ? " reasoning_effort" : "") +
    (version >= 5 ? " study_cards_added learning_focus card_format" : "") +
    (version >= 7 ? " model" : "") +
    (version >= 10 ? " context_enabled context_data" : "") +
    (version >= 11 ? " text_enabled occlusion_enabled image_completed_pages suggestions" : "") +
    (version >= 12 ? " visual_enabled purpose rundown_data" : "")
  );
}

function noteKeys(base: string, version: number): string {
  return (
    base +
    (version >= 5 ? " note_type" : "") +
    (version >= 6 ? " source_crop" : "") +
    (version >= 9 ? " occlusion" : "") +
    (version >= 12 ? " visual_masks" : "")
  );
}

const SUGGESTION_KEYS = "id page label reason original_mask mask front back status version card created_at";

/**
 * Validate a parsed manifest and return it upgraded to the current record
 * shape, in canonical order. Asset bytes are checked separately.
 */
export function upgradeManifest(raw: unknown): Manifest {
  requireKeys(raw, "format version lecture pages cards runs assets");
  const version = raw.version;
  const supported =
    (raw.format === RECALLOOM_FORMAT && isInt(version) && version >= 1 && version <= 12) ||
    (raw.format === SLANKI_FORMAT && version === SLANKI_VERSION);
  if (!supported) throw new WorkflowError("This is not a supported Slanki or Recalloom backup.");
  // Slanki v1 records use the Recalloom v12 structure.
  const level = raw.format === SLANKI_FORMAT ? 12 : (version as number);
  const info = raw.lecture;
  requireKeys(info, "id title sha256 original_name created_at");
  if (!isUuid(info.id)) throw invalid();
  const lecture: LectureRecord = {
    id: info.id,
    title: text(info.title, 180, { blank: false }),
    sha256: text(info.sha256, 64, { blank: false }),
    original_name: text(info.original_name, 255, { blank: false }),
    created_at: timestamp(info.created_at),
  };
  const rawPages = raw.pages;
  if (
    !Array.isArray(rawPages) ||
    rawPages.length < 1 ||
    rawPages.length > MAX_PAGES ||
    rawPages.some((page, i) => !isPlainObject(page) || page.number !== i + 1)
  ) {
    throw new WorkflowError("Backup page numbers are invalid.");
  }
  if (!Array.isArray(raw.cards) || !Array.isArray(raw.runs) || raw.cards.length > 10000 || raw.runs.length > 1000) {
    throw new WorkflowError("Backup contains too many records.");
  }
  const pages: PageRecord[] = rawPages.map((page) => {
    requireKeys(page, "number text width height warning");
    const record: PageRecord = {
      number: page.number as number,
      text: text(page.text, 25000),
      width: positive(page.width),
      height: positive(page.height),
      warning: text(page.warning, 300),
    };
    if (!(record.width > 0 && record.width <= 1500 && record.height > 0 && record.height <= 1500)) {
      throw new WorkflowError("Backup contains an invalid source page.");
    }
    return record;
  });
  const pageMap = new Map(pages.map((page) => [page.number, page]));
  const contextPages = pages.map((page) => ({ number: page.number, text: page.text, warning: page.warning }));

  const runs: RunRecord[] = [];
  const runIds = new Set<string>();
  const proposals = new Map<string, unknown[]>();
  for (const source of raw.runs as unknown[]) {
    requireKeys(source, runKeys(level));
    const r = { ...source };
    const suggestions = Object.hasOwn(r, "suggestions") ? r.suggestions : [];
    if (!Array.isArray(suggestions) || suggestions.length > 600) {
      throw new WorkflowError("Backup contains too many image suggestions.");
    }
    const textEnabled = Object.hasOwn(r, "text_enabled") ? r.text_enabled : true;
    const occlusionEnabled = Object.hasOwn(r, "occlusion_enabled") ? r.occlusion_enabled : false;
    const visualEnabled = Object.hasOwn(r, "visual_enabled") ? r.visual_enabled : false;
    const imagePages = Object.hasOwn(r, "image_completed_pages") ? r.image_completed_pages : [];
    if (
      typeof textEnabled !== "boolean" ||
      typeof occlusionEnabled !== "boolean" ||
      typeof visualEnabled !== "boolean" ||
      !(textEnabled || occlusionEnabled || visualEnabled) ||
      (occlusionEnabled && visualEnabled) ||
      ((occlusionEnabled || visualEnabled) && r.provider !== "codex") ||
      (!occlusionEnabled && suggestions.length) ||
      (!(occlusionEnabled || visualEnabled) && Array.isArray(imagePages) && imagePages.length)
    ) {
      throw new WorkflowError("Backup has invalid image generation settings.");
    }
    const contextEnabled = Object.hasOwn(r, "context_enabled") ? r.context_enabled : false;
    const contextData = Object.hasOwn(r, "context_data") ? r.context_data : {};
    checkedContext(contextData, contextEnabled, lecture.sha256, contextPages);
    const model = Object.hasOwn(r, "model") ? r.model : "";
    if (typeof model !== "string" || (model && !MODEL_ID.test(model))) {
      throw new WorkflowError("Choose a model from this CLI's model list.");
    }
    const cardLimit = Object.hasOwn(r, "card_limit") ? r.card_limit : null;
    if (cardLimit !== null && (!isInt(cardLimit) || cardLimit < 1 || cardLimit > 500)) {
      throw new WorkflowError("Backup contains an invalid card limit.");
    }
    const pageNumbers = validateRunPages(r.page_numbers, new Set(pageMap.keys()));
    const completed = validateRunPages(r.completed_pages, pageNumbers);
    const imageCompleted = validateRunPages(imagePages, pageNumbers);
    const cardsAdded = positive(r.cards_added);
    const studyCardsAdded = level < 5 ? cardsAdded : positive(r.study_cards_added);
    if ((occlusionEnabled || visualEnabled) && (cardLimit === null || suggestions.length + studyCardsAdded > cardLimit)) {
      throw new WorkflowError("Backup image proposals exceed their run's card limit.");
    }
    const purpose = Object.hasOwn(r, "purpose") ? r.purpose : "cards";
    const rundownData = Object.hasOwn(r, "rundown_data") ? r.rundown_data : {};
    if (
      (purpose !== "cards" && purpose !== "rundown") ||
      (purpose === "rundown" && (occlusionEnabled || visualEnabled || contextEnabled || cardsAdded || studyCardsAdded))
    ) {
      throw new WorkflowError("Invalid lecture rundown settings in backup.");
    }
    // Study-guide content is carried verbatim; Slanki no longer displays it.
    if (!isPlainObject(rundownData) || (purpose !== "rundown" && Object.keys(rundownData).length)) {
      throw new WorkflowError("Invalid lecture rundown settings in backup.");
    }
    const issues = validateRunIssues(Object.hasOwn(r, "issues") ? r.issues : [], completed);
    const reasoning = Object.hasOwn(r, "reasoning_effort") ? r.reasoning_effort : "";
    const focus = Object.hasOwn(r, "learning_focus") ? r.learning_focus : "balanced";
    const format = Object.hasOwn(r, "card_format") ? r.card_format : "basic";
    if (
      !isUuid(r.id) ||
      runIds.has(r.id) ||
      !(EFFORTS as readonly unknown[]).includes(reasoning) ||
      !Object.hasOwn(LEARNING_FOCUSES, focus as string) ||
      !(CARD_FORMATS as unknown[]).includes(format)
    ) {
      throw invalid();
    }
    let status = text(r.status, 16, { blank: false });
    let error = text(r.error, Number.MAX_SAFE_INTEGER);
    if (status === "queued" || status === "running") {
      status = "failed";
      error = "Generation was interrupted by backup/restore. Saved drafts are intact.";
    }
    const record: RunRecord = {
      id: r.id as string,
      status,
      provider: text(r.provider, 30, { blank: false }),
      model,
      page_numbers: pageNumbers,
      completed_pages: completed,
      context_enabled: contextEnabled as boolean,
      context_data: contextData as Record<string, unknown>,
      text_enabled: textEnabled,
      occlusion_enabled: occlusionEnabled,
      visual_enabled: visualEnabled,
      purpose: purpose as string,
      rundown_data: rundownData,
      image_completed_pages: imageCompleted,
      suggestions: [],
      issues,
      cards_added: cardsAdded,
      study_cards_added: studyCardsAdded,
      learning_focus: focus as string,
      card_format: format as string,
      card_limit: cardLimit as number | null,
      reasoning_effort: reasoning as string,
      filtered_count: level >= 3 ? positive(r.filtered_count) : 0,
      over_limit_count: level >= 3 ? positive(r.over_limit_count) : 0,
      error,
      created_at: timestamp(r.created_at),
      updated_at: timestamp(r.updated_at),
    };
    runIds.add(record.id);
    proposals.set(record.id, suggestions);
    runs.push(record);
  }

  const cards: CardRecord[] = [];
  const cardIds = new Set<string>();
  const fingerprints = new Set<string>();
  for (const source of raw.cards as unknown[]) {
    requireKeys(
      source,
      noteKeys("id page front back source_quote status fingerprint version anki_modified run created_at updated_at revisions", level),
    );
    const c = source;
    const noteType = Object.hasOwn(c, "note_type") ? c.note_type : "basic";
    if (!(NOTE_TYPES as readonly unknown[]).includes(noteType)) throw invalid();
    const page = pageMap.get(c.page as number);
    if (!isInt(c.page) || !page) throw invalid();
    const visualMasks = checkedVisualMasks(Object.hasOwn(c, "visual_masks") ? c.visual_masks : [], page, noteType as string);
    const sourceCrop = checkedCrop(Object.hasOwn(c, "source_crop") ? c.source_crop : {}, page);
    const occlusion = checkedOcclusion(Object.hasOwn(c, "occlusion") ? c.occlusion : {}, page, noteType as string, sourceCrop);
    const runId = c.run;
    if (runId !== null && (typeof runId !== "string" || !runIds.has(runId))) {
      throw new WorkflowError("Backup has an invalid generation reference.");
    }
    validateContent(c.front, c.back, c.source_quote, page, { noteType: noteType as string });
    if (
      !isUuid(c.id) ||
      cardIds.has(c.id) ||
      !["draft", "accepted", "rejected"].includes(c.status as string) ||
      typeof c.fingerprint !== "string" ||
      !c.fingerprint ||
      cpLength(c.fingerprint) > 64 ||
      fingerprints.has(c.fingerprint) ||
      !isInt(c.version) ||
      c.version < 0 ||
      !isInt(c.anki_modified) ||
      c.anki_modified < 0
    ) {
      throw invalid();
    }
    if (!Array.isArray(c.revisions) || c.revisions.length > 1000) {
      throw new WorkflowError("Backup contains too many card revisions.");
    }
    const versions = new Set<number>();
    const revisions = (c.revisions as unknown[]).map((rawRevision): RevisionRecord => {
      requireKeys(rawRevision, noteKeys("version front back source_quote status created_at", level));
      const revision = rawRevision;
      const revisionType = Object.hasOwn(revision, "note_type") ? revision.note_type : "basic";
      if (!(NOTE_TYPES as readonly unknown[]).includes(revisionType)) throw invalid();
      const crop = checkedCrop(Object.hasOwn(revision, "source_crop") ? revision.source_crop : {}, page);
      const masks = checkedVisualMasks(
        Object.hasOwn(revision, "visual_masks") ? revision.visual_masks : [],
        page,
        revisionType as string,
      );
      const mask = checkedOcclusion(
        Object.hasOwn(revision, "occlusion") ? revision.occlusion : {},
        page,
        revisionType as string,
        crop,
      );
      validateContent(revision.front, revision.back, revision.source_quote, page, { noteType: revisionType as string });
      if (!isInt(revision.version) || revision.version < 0 || versions.has(revision.version)) throw invalid();
      versions.add(revision.version);
      return {
        version: revision.version,
        front: revision.front as string,
        note_type: revisionType as string,
        visual_masks: masks,
        back: revision.back as string,
        source_quote: revision.source_quote as string,
        source_crop: crop,
        occlusion: mask,
        status: text(revision.status, 12, { blank: false }),
        created_at: timestamp(revision.created_at),
      };
    });
    revisions.sort((a, b) => a.version - b.version);
    cardIds.add(c.id);
    fingerprints.add(c.fingerprint);
    cards.push({
      id: c.id,
      page: page.number,
      front: c.front as string,
      note_type: noteType as CardRecord["note_type"],
      back: c.back as string,
      source_quote: c.source_quote as string,
      source_crop: sourceCrop,
      occlusion,
      visual_masks: visualMasks,
      status: c.status as CardRecord["status"],
      fingerprint: c.fingerprint,
      version: c.version,
      anki_modified: c.anki_modified,
      run: runId as string | null,
      created_at: timestamp(c.created_at),
      updated_at: timestamp(c.updated_at),
      revisions,
    });
  }

  for (const run of runs) {
    const page = run.image_completed_pages;
    run.suggestions = (proposals.get(run.id) ?? []).map((record) => {
      requireKeys(record, SUGGESTION_KEYS);
      if (
        !isUuid(record.id) ||
        !pageMap.has(record.page as number) ||
        !page.includes(record.page as number) ||
        !["pending", "accepted", "discarded"].includes(record.status as string) ||
        (record.status === "accepted") !== (record.card !== null) ||
        (record.card !== null && !cardIds.has(record.card as string))
      ) {
        throw invalid();
      }
      timestamp(record.created_at);
      return { ...record };
    });
  }

  cards.sort(compareNotes);
  runs.sort(compareNewest);
  return {
    format: SLANKI_FORMAT,
    version: SLANKI_VERSION,
    lecture,
    pages,
    cards,
    runs,
    assets: isPlainObject(raw.assets) ? (raw.assets as Record<string, string>) : {},
  };
}
