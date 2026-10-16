// Captures the mic as 16 kHz PCM16 (via AudioWorklet) and hands 40 ms chunks to a callback.
// Uses browser echo cancellation + noise suppression. Headphones are strongly recommended
// when translated voice is on, otherwise synthesized speech can leak back into the mic.

export class MicStreamer {
  private ctx?: AudioContext;
  private stream?: MediaStream;
  private node?: AudioWorkletNode;
  paused = false;

  async start(onChunk: (pcm: ArrayBuffer) => void, deviceId?: string): Promise<void> {
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: {
        echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1,
        ...(deviceId ? { deviceId: { ideal: deviceId } } : {}),
      },
    });
    this.ctx = new AudioContext({ latencyHint: "interactive" });
    await this.ctx.audioWorklet.addModule("/pcm-worklet.js");
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.ctx, "pcm-processor");
    this.node.port.onmessage = (e: MessageEvent<ArrayBuffer>) => {
      if (!this.paused) onChunk(e.data);
    };
    // Worklet needs a sink to keep running; route through a muted gain.
    const mute = this.ctx.createGain();
    mute.gain.value = 0;
    src.connect(this.node).connect(mute).connect(this.ctx.destination);
  }

  stop() {
    this.node?.disconnect();
    this.stream?.getTracks().forEach((t) => t.stop());
    void this.ctx?.close();
    this.node = undefined;
    this.stream = undefined;
    this.ctx = undefined;
  }
}
