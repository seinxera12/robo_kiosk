import { useEffect, useState } from "react";
import { config } from "./config";
import { SessionController } from "./services/SessionController";
import { AudioPlayer } from "./audio/AudioPlayer";
import { TimeoutGuard } from "./services/TimeoutGuard";
import { VoiceController } from "./audio/VoiceController";
import { PlaybackTracker } from "./services/PlaybackTracker";

export interface Session {
  controller: SessionController;
  voice: VoiceController;
}

/**
 * Owns SessionController + AudioPlayer + VoiceController + TimeoutGuard +
 * PlaybackTracker for the app's lifetime. Instantiated once; disposed on unmount.
 */
export function useSession(): Session | null {
  const [session, setSession] = useState<Session | null>(null);

  useEffect(() => {
    const player = new AudioPlayer();
    const guard = new TimeoutGuard();
    const tracker = new PlaybackTracker(player); // FE-12

    const controller = new SessionController({
      wsUrl: config.serverWsUrl,
      kioskId: config.kioskId,
      kioskLocation: config.kioskLocation,
      audio: {
        push: (d) => {
          tracker.onAudioFrame();
          player.push(d);
        },
        flush: () => {
          tracker.reset();
          player.flush();
        },
      },
      hooks: {
        onSend: () => guard.arm(),
        onResponseActivity: () => guard.disarm(),
        onFinal: () => {
          guard.disarm();
          tracker.onTextFinal(); // FE-12: text done; audio may still be playing
        },
      },
    });

    const voice = new VoiceController({
      sendUtterance: (pcm) => controller.sendUtterance(pcm),
    });

    controller.start();
    setSession({ controller, voice });

    return () => {
      guard.disarm();
      tracker.dispose();
      void voice.dispose();
      controller.dispose();
      player.dispose();
    };
  }, []);

  return session;
}
