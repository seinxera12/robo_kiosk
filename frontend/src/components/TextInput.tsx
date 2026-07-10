import { useState } from "react";
import { useStore } from "../store/useStore";
import type { SessionController } from "../services/SessionController";

/**
 * Text input (FE-5). Sends text_input{lang:"auto"}; user bubble is echoed
 * locally by the controller. Disabled until the connection is `ready`.
 */
export function TextInput({ controller }: { controller: SessionController }) {
  const [value, setValue] = useState("");
  const ready = useStore((s) => s.connection === "ready");

  function submit() {
    if (!ready) return;
    if (controller.sendText(value)) setValue("");
  }

  return (
    <form
      className="text-input"
      onSubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <input
        type="text"
        value={value}
        placeholder={ready ? "Type a message…" : "Connecting…"}
        disabled={!ready}
        onChange={(e) => setValue(e.target.value)}
        aria-label="Message"
      />
      <button type="submit" disabled={!ready || value.trim().length === 0}>
        Send
      </button>
    </form>
  );
}
