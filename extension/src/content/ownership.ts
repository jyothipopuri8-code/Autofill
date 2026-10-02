// Who owns each field's current value (doc §27) and the undo log (doc §28).
import type { Ownership } from "../shared/types";

interface State { ownership: Ownership; agentValue?: string }

export interface UndoEntry {
  key: string;
  kind: string;
  previous: string;
  next: string;
  ts: number;
  source: string;
  restore: () => Promise<boolean> | boolean;
  current: () => string;
}

export class OwnershipTracker {
  private states = new WeakMap<Element, State>();
  private batches: UndoEntry[][] = [];
  private listening = false;
  /** True while the agent itself is writing to the page, so its events never count as the user's. */
  busy = false;

  /** Watch for real user input. Events the agent dispatches are not trusted, so they never count. */
  attach(doc: Document): void {
    if (this.listening) return;
    this.listening = true;
    const onUser = (ev: Event) => {
      if (!ev.isTrusted || this.busy) return;
      const target = ev.target as Element | null;
      if (!target) return;
      this.noteUserEdit(target);
      // Radio/checkbox groups: any member counts for the whole group.
      const group = (target as HTMLInputElement).name ? target : null;
      if (group) this.noteUserEdit(group);
    };
    doc.addEventListener("input", onUser, true);
    doc.addEventListener("change", onUser, true);
    doc.addEventListener("click", (ev) => {
      if (!ev.isTrusted || this.busy) return;
      const t = ev.target as Element | null;
      if (t && t.closest("[role='option'],[role='listbox'],[role='combobox'],[aria-haspopup]")) {
        const host = t.closest("[role='combobox'],[aria-haspopup]");
        if (host) this.noteUserEdit(host);
      }
    }, true);
  }

  noteUserEdit(el: Element): void {
    const cur = this.states.get(el);
    if (cur?.ownership === "AGENT_FILLED") this.states.set(el, { ownership: "USER_MODIFIED_AGENT_VALUE" });
    else if (!cur || cur.ownership === "EMPTY" || cur.ownership === "SITE_DEFAULT") this.states.set(el, { ownership: "USER_FILLED" });
  }

  get(el: Element): Ownership | undefined {
    return this.states.get(el)?.ownership;
  }

  markAgent(el: Element, value: string): void {
    this.states.set(el, { ownership: "AGENT_FILLED", agentValue: value });
  }

  /** Forget agent ownership (after undo/clear) so the field can be filled again. */
  release(el: Element): void {
    this.states.delete(el);
  }

  // --- undo ---------------------------------------------------------------

  pushBatch(entries: UndoEntry[]): void {
    if (entries.length) this.batches.push(entries);
  }

  get lastBatchSize(): number {
    return this.batches.at(-1)?.length ?? 0;
  }

  /** Revert the last autofill. Only values the agent still owns and has not been changed by the user are touched. */
  async undoLast(): Promise<{ restored: number; skipped: number }> {
    const batch = this.batches.pop();
    return batch ? this.revert(batch) : { restored: 0, skipped: 0 };
  }

  async clearAll(): Promise<{ restored: number; skipped: number }> {
    const all = this.batches.splice(0).flat().reverse();
    return this.revert(all);
  }

  private async revert(entries: UndoEntry[]): Promise<{ restored: number; skipped: number }> {
    let restored = 0, skipped = 0;
    for (const e of [...entries].reverse()) {
      if (e.current() !== e.next) { skipped++; continue; } // the user (or the page) changed it since
      try { (await e.restore()) ? restored++ : skipped++; } catch { skipped++; }
    }
    return { restored, skipped };
  }
}
