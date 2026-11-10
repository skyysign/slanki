import { useEffect, useState } from "preact/hooks";
import { Library } from "./Library.tsx";
import { route, toast } from "./state.ts";
import { Workspace } from "./Workspace.tsx";
import { AiStatusPill } from "./ai/AiStatus.tsx";

export function App() {
  const [reload, setReload] = useState(false);
  useEffect(() => {
    const required = () => setReload(true);
    addEventListener("slanki:reload-required", required);
    return () => removeEventListener("slanki:reload-required", required);
  }, []);
  const current = route.value;
  return (
    <>
      <header class="topbar">
        <a class="brand" href="#/">
          <img src="./favicon.svg" alt="" />
          Slanki
        </a>
        <span class="spacer" />
        <AiStatusPill />
      </header>
      {reload && (
        <div class="banner warn" role="alert">
          Slanki was updated in another tab. <button class="btn small" onClick={() => location.reload()}>Reload</button>
        </div>
      )}
      <main>{current.name === "lecture" ? <Workspace key={current.id} id={current.id} /> : <Library />}</main>
      {toast.value && (
        <div class={`toast${toast.value.error ? " error" : ""}`} role={toast.value.error ? "alert" : "status"}>
          {toast.value.message}
        </div>
      )}
    </>
  );
}
