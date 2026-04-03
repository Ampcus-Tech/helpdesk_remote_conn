/**
 * Map pointer position inside a letterboxed `<video>` to stream coordinates.
 * Uses intrinsic dimensions as `screen_width` / `screen_height` for the host mapping.
 */
export function pointerToVideoFrame(
  clientX: number,
  clientY: number,
  video: HTMLVideoElement,
): { x: number; y: number; screen_width: number; screen_height: number } | null {
  const vw = video.videoWidth;
  const vh = video.videoHeight;
  if (!vw || !vh) return null;

  const rect = video.getBoundingClientRect();
  const scale = Math.min(rect.width / vw, rect.height / vh);
  const dispW = vw * scale;
  const dispH = vh * scale;
  const ox = rect.left + (rect.width - dispW) / 2;
  const oy = rect.top + (rect.height - dispH) / 2;

  const x = clientX - ox;
  const y = clientY - oy;
  if (x < 0 || y < 0 || x > dispW || y > dispH) return null;

  const nx = (x / dispW) * vw;
  const ny = (y / dispH) * vh;
  return { x: nx, y: ny, screen_width: vw, screen_height: vh };
}
