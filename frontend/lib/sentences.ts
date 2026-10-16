// Split streaming translation text into sentences that are safe to speak early.
// Returns the sentences that are complete and the index just past the last one.
const END = /[.!?।。！？]+["')\]]*\s+/g;

export function completedSentences(text: string, fromIndex: number): { sentences: string[]; next: number } {
  const slice = text.slice(fromIndex);
  const sentences: string[] = [];
  let last = 0;
  END.lastIndex = 0;
  let m: RegExpExecArray | null;
  while ((m = END.exec(slice)) !== null) {
    const s = slice.slice(last, m.index + m[0].length).trim();
    if (s) sentences.push(s);
    last = m.index + m[0].length;
  }
  return { sentences, next: fromIndex + last };
}

export function remainder(text: string, fromIndex: number): string {
  return text.slice(fromIndex).trim();
}
