// Timestamp ordering with microsecond precision (Django isoformat) and a stable
// tie-break, so every sort of notes and runs agrees across modules.

/** Microseconds since the epoch for ISO 8601 strings with an offset. */
export function timeKey(value: string): number {
  const iso = value.replace(" ", "T");
  const fraction = /\.(\d+)/.exec(iso)?.[1] ?? "";
  const micros = Number((fraction + "000000").slice(3, 6));
  return Date.parse(iso) * 1000 + micros;
}

export function compareCreated(a: { created_at: string; id: string }, b: { created_at: string; id: string }): number {
  return timeKey(a.created_at) - timeKey(b.created_at) || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

/** Notes in lecture order: page, then creation time. */
export function compareNotes(
  a: { page: number; created_at: string; id: string },
  b: { page: number; created_at: string; id: string },
): number {
  return a.page - b.page || compareCreated(a, b);
}

/** Newest first. */
export function compareNewest(a: { created_at: string; id: string }, b: { created_at: string; id: string }): number {
  return compareCreated(b, a);
}
