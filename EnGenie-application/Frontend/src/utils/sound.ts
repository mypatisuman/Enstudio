/**
 * Web Audio API Notification Sound Synthesizer
 * Generates an elegant, crystal-clear completion chime without external asset dependencies.
 */

let audioCtx: AudioContext | null = null;
let isAudioUnlocked = false;

function getAudioContext(): AudioContext | null {
  try {
    if (!audioCtx) {
      const AudioContextClass = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
      if (AudioContextClass) {
        audioCtx = new AudioContextClass();
      }
    }
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume();
    }
    return audioCtx;
  } catch (err) {
    console.warn("[Sound] Could not initialize Web Audio Context:", err);
    return null;
  }
}

// Automatically unlock AudioContext on user interaction
if (typeof window !== "undefined") {
  const unlockAudio = () => {
    if (!isAudioUnlocked) {
      const ctx = getAudioContext();
      if (ctx && ctx.state === "running") {
        isAudioUnlocked = true;
        window.removeEventListener("click", unlockAudio);
        window.removeEventListener("keydown", unlockAudio);
        window.removeEventListener("touchstart", unlockAudio);
      }
    }
  };

  window.addEventListener("click", unlockAudio, { passive: true });
  window.addEventListener("keydown", unlockAudio, { passive: true });
  window.addEventListener("touchstart", unlockAudio, { passive: true });
}

/**
 * Plays a pleasant, professional dual-tone chime (D5 -> A5 with harmonic resonance).
 */
export function playNotificationSound(): void {
  try {
    const ctx = getAudioContext();
    if (!ctx) return;

    const now = ctx.currentTime;

    // Master Gain for smooth volume control
    const masterGain = ctx.createGain();
    masterGain.gain.setValueAtTime(0.25, now);
    masterGain.connect(ctx.destination);

    // Primary Tone: D5 (587.33 Hz)
    const osc1 = ctx.createOscillator();
    const gain1 = ctx.createGain();
    osc1.type = "sine";
    osc1.frequency.setValueAtTime(587.33, now);
    gain1.gain.setValueAtTime(0.01, now);
    gain1.gain.exponentialRampToValueAtTime(0.4, now + 0.04);
    gain1.gain.exponentialRampToValueAtTime(0.001, now + 0.45);
    osc1.connect(gain1);
    gain1.connect(masterGain);

    // Harmonic Ascent Tone: A5 (880.00 Hz)
    const osc2 = ctx.createOscillator();
    const gain2 = ctx.createGain();
    osc2.type = "sine";
    osc2.frequency.setValueAtTime(880.0, now + 0.12);
    gain2.gain.setValueAtTime(0.01, now + 0.12);
    gain2.gain.exponentialRampToValueAtTime(0.5, now + 0.16);
    gain2.gain.exponentialRampToValueAtTime(0.001, now + 0.85);
    osc2.connect(gain2);
    gain2.connect(masterGain);

    // Shimmer / Soft Overtone: D6 (1174.66 Hz)
    const osc3 = ctx.createOscillator();
    const gain3 = ctx.createGain();
    osc3.type = "triangle";
    osc3.frequency.setValueAtTime(1174.66, now + 0.15);
    gain3.gain.setValueAtTime(0.01, now + 0.15);
    gain3.gain.exponentialRampToValueAtTime(0.15, now + 0.18);
    gain3.gain.exponentialRampToValueAtTime(0.001, now + 0.7);
    osc3.connect(gain3);
    gain3.connect(masterGain);

    // Start & Stop Oscillators
    osc1.start(now);
    osc1.stop(now + 0.5);

    osc2.start(now + 0.12);
    osc2.stop(now + 0.9);

    osc3.start(now + 0.15);
    osc3.stop(now + 0.8);
  } catch (err) {
    console.warn("[Sound] Error playing notification sound:", err);
  }
}
