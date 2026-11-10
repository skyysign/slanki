// Text-batch planning from generation.py perform_run: batch size and the
// cumulative per-batch ceiling that carries unused room forward.

export function minimumCards(cardFormat: string): number {
  return cardFormat === "reversed" ? 2 : 1;
}

export function batchSize(selectedPageCount: number, cardLimit: number | null, cardFormat: string): number {
  if (!cardLimit) return 3;
  const slots = Math.max(1, Math.floor(cardLimit / minimumCards(cardFormat)));
  return Math.max(3, Math.ceil(selectedPageCount / slots));
}

/**
 * Ceiling for the next batch. `completedCount` includes pages finished earlier
 * in this run (also before a resume); `studyCardsAdded` counts this run's cards.
 */
export function batchLimit(
  cardLimit: number,
  completedCount: number,
  batchLength: number,
  selectedPageCount: number,
  studyCardsAdded: number,
): number {
  const processed = completedCount + batchLength;
  return Math.max(0, Math.floor((cardLimit * processed) / selectedPageCount) - studyCardsAdded);
}

export function batches<T>(items: readonly T[], size: number): T[][] {
  const result: T[][] = [];
  for (let start = 0; start < items.length; start += size) result.push(items.slice(start, start + size));
  return result;
}
