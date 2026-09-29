/* The camera's capture time from a photo's EXIF (JPEG APP1, or a TIFF's own IFDs), read in the page before the upload
   so the time box can be filled in. Only the few bytes of the header and the IFDs are read, never the whole file. */
window.LA_EXIF = (() => {
  'use strict';
  const pad = (n) => String(n).padStart(2, '0');
  const local = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;

  async function bytes(blob, off, len) {
    if (off < 0 || off >= blob.size) throw new Error('outside the file');
    return new DataView(await blob.slice(off, Math.min(blob.size, off + len)).arrayBuffer());
  }

  // the TIFF structure starting at base in blob -> { original, digitised, offset } (EXIF strings, or undefined)
  async function tiffTags(blob, base) {
    const h = await bytes(blob, base, 8);
    const le = h.getUint16(0) === 0x4949;
    if (!le && h.getUint16(0) !== 0x4d4d) return {};
    const u16 = (v, o) => v.getUint16(o, le), u32 = (v, o) => v.getUint32(o, le);
    async function ifd(off) {                                  // tag -> [type, count, value field, its position]
      const n = u16(await bytes(blob, base + off, 2), 0);
      if (n > 1000) throw new Error('not an IFD');
      const v = await bytes(blob, base + off + 2, n * 12), out = {};
      for (let i = 0; i + 12 <= v.byteLength; i += 12) out[u16(v, i)] = [u16(v, i + 2), u32(v, i + 4), u32(v, i + 8), off + 2 + i + 8];
      return out;
    }
    async function ascii(e) {
      if (!e || e[0] !== 2 || e[1] > 64) return undefined;
      const v = e[1] <= 4 ? await bytes(blob, base + e[3], e[1]) : await bytes(blob, base + e[2], e[1]);
      let s = '';
      for (let i = 0; i < v.byteLength && v.getUint8(i); i++) s += String.fromCharCode(v.getUint8(i));
      return s;
    }
    const ifd0 = await ifd(u32(h, 4));
    const t = { changed: await ascii(ifd0[0x0132]) };
    if (ifd0[0x8769]) {
      const ex = await ifd(ifd0[0x8769][2]);
      t.original = await ascii(ex[0x9003]);
      t.offset = await ascii(ex[0x9011]) || await ascii(ex[0x9010]);
    }
    return t;
  }

  // where the TIFF structure starts: 0 for a TIFF, after 'Exif\0\0' in a JPEG's APP1, else -1
  async function tiffStart(blob) {
    const h = await bytes(blob, 0, 4);
    if (h.getUint32(0) === 0x49492a00 || h.getUint32(0) === 0x4d4d002a) return 0;
    if (h.getUint16(0) !== 0xffd8) return -1;
    for (let p = 2; p + 4 <= blob.size;) {
      const m = await bytes(blob, p, 10);
      if (m.getUint8(0) !== 0xff) return -1;
      const kind = m.getUint8(1), len = m.getUint16(2);
      if (kind === 0xda || kind === 0xd9) return -1;                 // the image data: no EXIF before it
      if (kind === 0xe1 && m.byteLength >= 10 && m.getUint32(4) === 0x45786966 && m.getUint16(8) === 0) return p + 10;
      p += 2 + len;
    }
    return -1;
  }

  // blob -> { when: 'YYYY-MM-DDTHH:MM' for <input type=datetime-local>, in this computer's time zone;
  //           zone: the camera's UTC offset ('+02:00') when it recorded one, else null (the clock is taken as local) }
  //         or null when the photo has no usable time
  async function captureTime(blob) {
    try {
      const at = await tiffStart(blob);
      if (at < 0) return null;
      const t = await tiffTags(blob, at);
      const m = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}):(\d{2})/.exec(t.original || t.changed || '');
      if (!m || +m[1] < 1900 || +m[2] < 1 || +m[2] > 12 || +m[3] < 1 || +m[3] > 31 || +m[4] > 23 || +m[5] > 59) return null;
      const z = /^([+-])(\d{2}):(\d{2})$/.exec(t.offset || '');
      if (!z) return { when: `${m[1]}-${m[2]}-${m[3]}T${m[4]}:${m[5]}`, zone: null };
      const sign = z[1] === '-' ? -1 : 1;
      const utc = Date.UTC(+m[1], m[2] - 1, +m[3], +m[4], +m[5]) - sign * (z[2] * 60 + +z[3]) * 60000;
      return { when: local(new Date(utc)), zone: z[0] };
    } catch (e) {                                  // a damaged or odd header: no time, the box stays empty
      return null;
    }
  }
  return { captureTime };
})();
