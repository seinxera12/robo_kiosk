/**
 * TimeoutGuard (FE-13).
 *
 * After a request is sent, arm a timeout. If no inbound activity (transcript or
 * llm_text_chunk) arrives within N seconds, surface a soft error, close any
 * open assistant bubble, and re-enable input — recovering the hang the desktop
 * client lacks on total LLM failure (REF §3.7, §10, #5).
 *
 * N must exceed worst-case cold-start first-token (Kokoro/e5 lazy load, REF
 * §9.4/§10 give no hard number — OQ-6). Default 20 s, configurable.
 */
import { actions, getSnapshot } from "../store/store";

export class TimeoutGuard {
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly timeoutMs = 20000) {}

  /** Called on send (FE-13 arms the timer). */
  arm(): void {
    this.clear();
    actions.setSoftError(null);
    this.timer = setTimeout(() => this.fire(), this.timeoutMs);
  }

  /** Called on any relevant inbound activity — cancels the timer. */
  disarm(): void {
    this.clear();
  }

  private fire(): void {
    this.timer = null;
    // Close any dangling assistant bubble so the UI isn't stuck mid-stream.
    if (getSnapshot().responseStarted) actions.finishAssistantResponse();
    actions.setStatus("listening");
    actions.setSoftError(
      "The assistant didn't respond. Please try again."
    );
  }

  private clear(): void {
    if (this.timer) {
      clearTimeout(this.timer);
      this.timer = null;
    }
  }
}
