// AudioWorklet: resample mic audio to 16 kHz mono PCM16 and post 40 ms chunks.
class PCMProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.pos = 0;
    this.carry = new Float32Array(0);
    this.out = [];
    this.chunk = 640; // 40 ms @ 16 kHz
  }

  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;

    const buf = new Float32Array(this.carry.length + ch.length);
    buf.set(this.carry, 0);
    buf.set(ch, this.carry.length);

    let p = this.pos;
    while (p + 1 < buf.length) {
      const i = Math.floor(p);
      const f = p - i;
      this.out.push(buf[i] * (1 - f) + buf[i + 1] * f);
      p += this.ratio;
    }
    const used = Math.floor(p);
    this.carry = buf.slice(used);
    this.pos = p - used;

    while (this.out.length >= this.chunk) {
      const pcm = new Int16Array(this.chunk);
      for (let i = 0; i < this.chunk; i++) {
        const s = Math.max(-1, Math.min(1, this.out[i]));
        pcm[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
      }
      this.out = this.out.slice(this.chunk);
      this.port.postMessage(pcm.buffer, [pcm.buffer]);
    }
    return true;
  }
}

registerProcessor("pcm-processor", PCMProcessor);
