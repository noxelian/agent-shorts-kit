// Deterministic hash-based PRNG. Remotion forbids Math.random / Date.now, so all
// "randomness" in the motion pack is derived from integer seeds (scene index,
// frame, cell id). Same seeds -> same output on every render pass.

const UINT = 4294967296;

// Integer hash of two seeds -> uint32. Cheap avalanche mix (xorshift-multiply).
export const hashInt = (a: number, b: number): number => {
  let h = Math.imul(a | 0, 374761393) + Math.imul(b | 0, 668265263);
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return h >>> 0;
};

export const hash3 = (a: number, b: number, c: number): number =>
  hashInt(hashInt(a, b), c);

// Uniform value in [0, 1) from two integer seeds.
export const rand01 = (a: number, b: number): number => hashInt(a, b) / UINT;

// Uniform value in [0, 1) from three integer seeds.
export const rand01n = (a: number, b: number, c: number): number =>
  hash3(a, b, c) / UINT;
