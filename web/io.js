// Fetch a binary data file. The published site ships gzip-compressed copies (name.gz,
// written by `python -m lunarops.pack`); a local build may only have the raw file.
export async function fetchBin(path) {
  for (const url of [path + ".gz", path]) {
    let r;
    try { r = await fetch(url, { cache: "no-cache" }); } catch { continue; }
    if (!r.ok) continue;
    const buf = new Uint8Array(await r.arrayBuffer());
    if (buf[0] === 0x1f && buf[1] === 0x8b) {                       // gzip magic: decompress in the browser
      if (typeof DecompressionStream === "function") {
        const ds = new Blob([buf]).stream().pipeThrough(new DecompressionStream("gzip"));
        return await new Response(ds).arrayBuffer();
      }
      // older browsers (Safari < 16.4): a small, well-known inflater (fflate, MIT) from the CDN
      const { gunzipSync } = await import("https://cdn.jsdelivr.net/npm/fflate@0.8.2/esm/browser.js");
      return gunzipSync(buf).buffer;
    }
    return buf.buffer;                                               // server already decoded it, or raw file
  }
  throw new Error(`missing data file ${path}`);
}
