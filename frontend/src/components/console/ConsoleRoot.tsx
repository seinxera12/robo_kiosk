import { useSession } from "../../useSession";
import { useStore } from "../../store/useStore";
import { TopBar } from "./TopBar";
import { Transcript } from "./Transcript";
import { InputVisualizer } from "./InputVisualizer";
import { SystemTrace } from "./SystemTrace";
import { Composer } from "./Composer";

/**
 * Neo-HUD console shell (spec §2). Owns the same session lifecycle as the
 * old <App/> via useSession (SessionController + AudioPlayer + VoiceController
 * + TimeoutGuard + PlaybackTracker), so store state (connection, bubbles,
 * trace log, etc.) is real. All panels are now fully wired: text/voice
 * send-receive, mic visualizer, system trace, and TTS playback/mute.
 */
export function ConsoleRoot() {
  const session = useSession();
  const softError = useStore((s) => s.softError);

  return (
    <div id="console-root">
      <TopBar />

      {softError && (
        <div className="console-soft-error" role="alert">
          {softError}
        </div>
      )}

      {session ? (
        <InputVisualizer voice={session.voice} />
      ) : (
        <section className="console-panel panel-left">
          <header className="console-panel-header">
            <span className="status-dot" />
            Mic Input
          </header>
          <div className="console-panel-body" />
        </section>
      )}

      <Transcript />

      <SystemTrace />

      <section className="console-panel panel-bottom">
        {session && (
          <Composer
            controller={session.controller}
            voice={session.voice}
            player={session.player}
          />
        )}
      </section>
    </div>
  );
}
