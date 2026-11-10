import { useEffect, useRef, useState } from "preact/hooks";
import { timeKey } from "../core/time.ts";
import type { ExtractProgress } from "../pdf/extract.ts";
import { importPdfFile, restoreBackupFile, saveLibraryBackup } from "../services/lectures.ts";
import { listLectures, onLibraryChange, type LectureSummary } from "../store/library.ts";
import { plural, useBusy } from "./components.tsx";
import { notify, openLecture, reportError } from "./state.ts";

function needsBackup(summary: LectureSummary): boolean {
  const { backed_up_at, updated_at } = summary.lecture;
  return !backed_up_at || timeKey(backed_up_at) < timeKey(updated_at);
}

export function Library() {
  const [lectures, setLectures] = useState<LectureSummary[] | null>(null);
  const [progress, setProgress] = useState<(ExtractProgress & { name: string }) | null>(null);
  const [over, setOver] = useState(false);
  const [busy, run] = useBusy();
  const pdfInput = useRef<HTMLInputElement>(null);
  const backupInput = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let live = true;
    const load = () => void listLectures().then((value) => live && setLectures(value), reportError);
    load();
    const stop = onLibraryChange(load);
    return () => {
      live = false;
      stop();
    };
  }, []);

  const importPdf = (file: File | undefined) =>
    file &&
    run(async () => {
      try {
        setProgress({ name: file.name, page: 0, pages: 0 });
        const result = await importPdfFile(file, (value) => setProgress({ ...value, name: file.name }));
        if (!result.created) notify("You already added this PDF. Opening it.");
        openLecture(result.id);
      } catch (error) {
        reportError(error);
      } finally {
        setProgress(null);
      }
    });

  const restore = (file: File | undefined) =>
    file &&
    run(async () => {
      try {
        const result = await restoreBackupFile(file);
        if (result.opened) {
          notify("Backup restored.");
          openLecture(result.opened);
        } else {
          const skipped = result.skipped ? `, ${plural(result.skipped, "lecture")} already in your library` : "";
          notify(`Restored ${plural(result.restored, "lecture")}${skipped}.`);
        }
      } catch (error) {
        reportError(error);
      }
    });

  return (
    <>
      <section class="hero">
        <h1>Turn lecture slides into Anki cards</h1>
        <p class="muted">
          Add a PDF, let your own AI draft cards, check them beside the slide, and export to Anki. Your files stay in this browser.
        </p>
      </section>

      {progress ? (
        <div class="drop" aria-live="polite">
          <strong>Reading {progress.name}…</strong>
          <span class="muted">{progress.pages ? `Slide ${progress.page} of ${progress.pages}` : "Opening the PDF"}</span>
          <div class="progress" style={{ width: "min(360px, 80%)" }}>
            <div style={{ width: progress.pages ? `${(progress.page / progress.pages) * 100}%` : "4%" }} />
          </div>
        </div>
      ) : (
        <button
          type="button"
          class={`drop${over ? " over" : ""}`}
          onClick={() => pdfInput.current?.click()}
          onDragOver={(event) => {
            event.preventDefault();
            setOver(true);
          }}
          onDragLeave={() => setOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setOver(false);
            const file = [...(event.dataTransfer?.files ?? [])].find((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
            if (file) void importPdf(file);
            else notify("Drop a PDF file. Export PowerPoint or Keynote slides as PDF first.", true);
          }}
          disabled={busy}
        >
          <span class="icon" aria-hidden="true">📄</span>
          <strong>Drop a lecture PDF here</strong>
          <span class="muted small">or click to choose a file · up to 100 slides · nothing is uploaded</span>
        </button>
      )}
      <input
        ref={pdfInput}
        class="sr-only"
        type="file"
        accept="application/pdf,.pdf"
        tabIndex={-1}
        onChange={(event) => {
          const input = event.currentTarget;
          void importPdf(input.files?.[0]);
          input.value = "";
        }}
      />
      <input
        ref={backupInput}
        class="sr-only"
        type="file"
        accept=".zip,application/zip"
        tabIndex={-1}
        onChange={(event) => {
          const input = event.currentTarget;
          void restore(input.files?.[0]);
          input.value = "";
        }}
      />

      <div class="section-head">
        <h2>Your lectures</h2>
        <span class="spacer" />
        {!!lectures?.length && (
          <button
            class="btn small"
            disabled={busy}
            title="One file with every lecture, its slides, cards and history"
            onClick={() =>
              run(async () => {
                try {
                  const count = await saveLibraryBackup();
                  notify(`Backup of ${plural(count, "lecture")} downloaded.`);
                } catch (error) {
                  reportError(error);
                }
              })
            }
          >
            Back up all lectures
          </button>
        )}
        <button class="btn small" disabled={busy} onClick={() => backupInput.current?.click()}>
          Restore a backup
        </button>
      </div>

      {lectures === null ? (
        <p class="muted">Loading…</p>
      ) : lectures.length === 0 ? (
        <div class="empty">
          <p>
            <strong>No lectures yet.</strong>
          </p>
          <p class="muted small">
            Add a PDF above, or restore a backup from Slanki or Recalloom.
          </p>
        </div>
      ) : (
        <div class="lecture-list">
          {lectures.map((summary) => (
            <a class="lecture-card" href={`#/lecture/${summary.lecture.id}`} key={summary.lecture.id}>
              <h3>{summary.lecture.title}</h3>
              <div class="counts">
                {summary.toReview > 0 && <span class="badge review">{summary.toReview} to review</span>}
                <span class="badge ready">{plural(summary.readyCards, "Anki card")} ready</span>
                {summary.running && <span class="badge review">Making cards…</span>}
                {needsBackup(summary) && summary.ready + summary.toReview > 0 && <span class="badge warn">No recent backup</span>}
              </div>
              <span class="muted small">{plural(summary.lecture.page_count, "slide")}</span>
            </a>
          ))}
        </div>
      )}
      <p class="note-box" style={{ marginTop: "28px" }}>
        Lectures are stored only in this browser on this device. Clearing site data removes them, so use Back up all lectures (or a lecture's ··· menu) to keep a copy or move them to another browser.
      </p>
    </>
  );
}
